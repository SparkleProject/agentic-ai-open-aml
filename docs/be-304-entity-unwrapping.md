# BE-304: Entity Unwrapping & Corporate Structure Analysis — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Tranche 2 entities (real estate, legal, accounting firms) frequently deal with complex corporate structures: trusts, shell companies, multi-layered holding companies. Identifying the **Ultimate Beneficial Owner (UBO)** is a core regulatory requirement — AUSTRAC requires reporting entities to take "reasonable steps" to verify beneficial ownership.

BE-304 builds the **Entity Unwrapping** subsystem that:
1. Connects to company registries (ASIC for Australia, NZBN for New Zealand) to retrieve corporate ownership data.
2. Recursively traverses ownership layers until UBOs are identified (individuals owning ≥25% directly or indirectly).
3. Builds a graph structure representing the full ownership hierarchy.
4. Detects risk indicators: circular ownership, nominee directors, high-risk jurisdiction entities, dormant companies.
5. Exposes the graph for visualisation in the FE `CorporateVisualiser` component.

### Dependencies on Existing Code
- `src/aml/db/models/customer.py` — `Customer` model (`customer_type: ENTITY`).
- `src/aml/agents/specialized/base.py` — `CDDAgent` (will gain new tools for entity unwrapping).
- `src/aml/agents/tools/protocol.py` — `BaseTool` interface.

### Frontend Context
- `src/components/KYC/CorporateStructure/CorporateVisualiser.tsx` — Interactive graph using React Flow. Uses `mockCorporateData.ts`.
- `src/components/KYC/CorporateStructure/EntityNode.tsx` — Custom node renderer with risk indicators.
- `src/components/KYC/CorporateStructure/EntityDetailPanel.tsx` — Side panel showing entity details.
- The FE expects a node/edge graph structure: `{ nodes: EntityNode[], edges: OwnershipEdge[] }`.

---

## 2. Architecture Approach: Graph-Based Recursive Resolution

```
  Entity ──> Registry Adapter ──> Ownership Parser ──> Recursive Resolver ──> Graph Builder ──> Risk Annotator
  (ASIC/NZBN)                     (directors,           (follow ownership      (nodes + edges)   (flags, scores)
                                   shareholders)         until UBO or depth)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Corporate Structure Data Models

**Files:**
- `src/aml/services/entity/models.py`

**Implementation Details:**
- Define graph node and edge models:
  ```python
  class CorporateEntity(BaseModel):
      entity_id: str           # Registry ID (ACN for ASIC, NZBN for NZ)
      name: str
      entity_type: str         # company, trust, partnership, individual
      jurisdiction: str        # AU, NZ, etc.
      status: str              # active, deregistered, struck_off
      registration_date: str | None
      directors: list[Director]
      shareholders: list[Shareholder]
      risk_flags: list[str]    # nominee_director, high_risk_jurisdiction, etc.

  class Shareholder(BaseModel):
      name: str
      entity_id: str | None    # If the shareholder is itself a company
      ownership_percentage: float
      shareholder_type: str    # individual, company, trust

  class OwnershipEdge(BaseModel):
      source_id: str           # Parent entity
      target_id: str           # Child entity or individual
      ownership_percentage: float
      relationship_type: str   # direct_ownership, beneficial, nominee

  class OwnershipGraph(BaseModel):
      root_entity_id: str
      entities: dict[str, CorporateEntity]
      edges: list[OwnershipEdge]
      ubos: list[UBO]          # Identified UBOs
      max_depth_reached: int
      risk_summary: dict[str, Any]
  ```
- `UBO` model: `name: str`, `entity_id: str`, `effective_ownership: float`, `path: list[str]`, `risk_flags: list[str]`.

**Why:** These models serve both the backend graph analysis and the frontend visualisation. The `OwnershipGraph` response shape maps directly to the React Flow data format expected by `CorporateVisualiser.tsx`.

### Step 2: Implement Registry Adapter Protocol and Providers

**Files:**
- `src/aml/services/entity/registry/protocol.py`
- `src/aml/services/entity/registry/mock.py`
- `src/aml/services/entity/registry/asic.py` (stub)
- `src/aml/services/entity/registry/nzbn.py` (stub)

**Implementation Details:**
- Define `CompanyRegistryAdapter` protocol:
  - `async lookup(entity_id: str) -> CorporateEntity | None`
  - `async search(name: str, jurisdiction: str) -> list[CorporateEntity]`
- `MockRegistryAdapter`: returns configurable test data with multi-layered ownership for development.
- `ASICAdapter` (stub):
  - Calls the ASIC Connect API (`https://connectonline.asic.gov.au/`).
  - Maps ACN/ABN lookups to `CorporateEntity`.
  - Extracts directors and shareholders from the company extract.
- `NZBNAdapter` (stub):
  - Calls the NZBN API (`https://api.business.govt.nz/`).
  - Maps NZBN lookups to `CorporateEntity`.
- Factory: `get_registry_adapter(jurisdiction: str, settings: Settings) -> CompanyRegistryAdapter`.

**Why:** Registry APIs are jurisdiction-specific and require different authentication and response parsing. Stubs allow pipeline development while API access is obtained. The mock adapter provides complex test scenarios (circular ownership, deep nesting).

### Step 3: Build Recursive Ownership Resolver

**Files:**
- `src/aml/services/entity/resolver.py`

**Implementation Details:**
- Implement `OwnershipResolver`:
  - `async resolve(entity_id: str, jurisdiction: str, max_depth: int = 5) -> OwnershipGraph`
  - BFS/DFS traversal algorithm:
    1. Start with the root entity. Fetch its shareholders via the registry adapter.
    2. For each shareholder that is itself a company/trust, recursively fetch *its* shareholders.
    3. Continue until:
       - An individual UBO is found (natural person).
       - The ownership drops below the configurable threshold (default 25%).
       - Max depth is reached.
       - A circular reference is detected (entity A owns B owns A).
    4. Build the `OwnershipGraph` from the traversal.
  - **Effective ownership calculation**: multiply ownership percentages along the chain. E.g., Company A owns 50% of B, B owns 80% of C → A's effective ownership of C is 40%.
  - **Circular reference detection**: maintain a visited set. If an entity is revisited, flag it as `circular_ownership` and stop recursion on that branch.
  - **Caching**: cache registry lookups (TTL: 24 hours) to avoid redundant API calls when multiple customers share parent entities.

**Why:** Recursive resolution is the core algorithm. The 25% UBO threshold aligns with AUSTRAC's beneficial ownership requirements. Circular reference detection prevents infinite loops and flags suspicious structures. Caching reduces API costs and latency.

### Step 4: Implement Risk Annotator

**Files:**
- `src/aml/services/entity/risk_annotator.py`

**Implementation Details:**
- Implement `EntityRiskAnnotator`:
  - `annotate(graph: OwnershipGraph) -> OwnershipGraph`
  - Scans the graph for risk indicators and adds flags to each entity's `risk_flags`:
    - `nominee_director`: director appears in known nominee databases or appears as director in >20 companies.
    - `high_risk_jurisdiction`: entity registered in FATF grey/black list jurisdiction.
    - `dormant_company`: registered but no recent filings or activity.
    - `circular_ownership`: detected during resolution.
    - `shell_company_indicators`: no employees, no physical address, recently incorporated.
    - `complex_structure`: >3 ownership layers.
  - Computes `risk_summary` on the graph: total entities, max depth, number of flagged entities, UBO count.

**Why:** Risk flags transform raw ownership data into actionable compliance intelligence. These flags inform the CDDAgent's assessment and the risk scoring engine (BE-302).

### Step 5: Create Entity Unwrapping Tool for the CDDAgent

**Files:**
- `src/aml/agents/tools/local/entity_unwrap.py`
- `src/aml/agents/specialized/base.py` (update)

**Implementation Details:**
- Implement `EntityUnwrapTool(BaseTool)`:
  - `name`: `EntityUnwrapTool`
  - `description`: "Resolves the corporate ownership structure of an entity, identifying Ultimate Beneficial Owners (UBOs) and risk flags."
  - `input_schema`: `{ "entity_name": "...", "entity_id": "...", "jurisdiction": "AU" | "NZ" }`
  - `execute()`: calls `OwnershipResolver.resolve()` and returns the `OwnershipGraph` as JSON.
- Register in `ToolRegistry` during app startup.
- Update `CDDAgent.tool_whitelist` to include `EntityUnwrapTool`.

**Why:** This gives the CDDAgent the ability to autonomously investigate corporate structures during an investigation. When the agent encounters a complex entity, it can call this tool to resolve the ownership chain.

### Step 6: Create Entity API Router

**Files:**
- `src/aml/api/routers/entities.py`

**Implementation Details:**
- `GET /api/v1/entities/{entity_id}/ownership` — Returns the full `OwnershipGraph` for visualisation.
  - Query params: `jurisdiction`, `max_depth`.
  - Response shape matches the FE `CorporateVisualiser` expected input.
- `GET /api/v1/entities/search` — Searches company registries by name.
  - Query params: `name`, `jurisdiction`.
- `GET /api/v1/entities/{entity_id}/ubos` — Returns just the UBO list with effective ownership and paths.
- Register in `app.py`.

**Why:** The FE `KYCDetail.tsx` page navigates to a corporate structure view using `CorporateVisualiser.tsx`. The API must return graph data (nodes and edges) in the format the React Flow component expects.

### Step 7: Implement Tests

**Files:**
- `tests/test_entity_resolver.py`
- `tests/test_entity_risk.py`

**Implementation Details:**
- Test resolution with mock registry: simple chain (A → B → Individual), verify UBO identification.
- Test circular ownership: A → B → A, verify detection and termination.
- Test effective ownership calculation: multi-layer percentages.
- Test risk annotation: high-risk jurisdiction detection, nominee director detection.
- Test max depth limit: deep chains stop at configured depth.
- API test: verify graph response shape matches FE expectations.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **ASIC/NZBN API rate limits** | Medium | Request caching (24h TTL). Exponential backoff. Bulk lookups during off-peak. |
| **Deep/complex structures causing timeout** | Medium | Max depth limit (default 5). Background processing for structures > depth 3. |
| **Circular ownership infinite loops** | High | Visited-set detection. Hard recursion limit. |
| **Incomplete registry data** | Medium | Flag entities with missing shareholder data as `incomplete_data` risk. Prompt analyst for manual verification. |
