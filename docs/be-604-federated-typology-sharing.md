# BE-604: Federated Typology Sharing — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Money laundering patterns (typologies) evolve constantly. A structuring technique discovered by one tenant could protect all tenants on the platform — if they can share the pattern without exposing sensitive data. BE-604 implements a **federated typology sharing** system inspired by Tookitaki's approach.

The system must:
1. Allow tenants to share abstract money laundering patterns (typologies) without exposing PII or transaction data.
2. Enable the community to contribute and curate typologies.
3. Integrate shared typologies into the configurable rule engine (BE-305).
4. Version-control typologies for audit trail and rollback.
5. Maintain privacy: no raw data leaves the tenant boundary.

### Dependencies on Existing Code
- `src/aml/services/monitoring/rules.py` (from BE-206/BE-305) — `MonitoringRule` model.
- `src/aml/services/monitoring/rule_management.py` (from BE-305) — `RuleManagementService`.
- `src/aml/db/models/tenant.py` — tenant isolation.
- `src/aml/services/rag/service.py` — RAG pipeline for typology documentation.

---

## 2. Architecture Approach: Privacy-Preserving Pattern Library

```
  Tenant detects pattern ──> Abstract & Anonymize ──> Typology Record ──> Community Library
                                                            │                    │
                                                      No PII / tx data     Opt-in adoption
                                                      Only the pattern     per tenant
                                                      definition
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Typology Data Models

**Files:**
- `src/aml/db/models/typology.py`

**Implementation Details:**
- `Typology` ORM model:
  - `typology_id: str` — unique identifier (e.g., `TYP-2026-001`)
  - `name: str` — human-readable name (e.g., "Cross-border structuring via crypto exchanges")
  - `description: str` — detailed pattern description
  - `category: str` — classification: `structuring`, `layering`, `trade_based`, `crypto`, `real_estate`, `professional_services`, `elder_abuse`
  - `risk_level: str` — LOW, MEDIUM, HIGH, CRITICAL
  - `indicators: list[str]` — observable characteristics (e.g., "Multiple deposits just under reporting threshold", "Funds moved through multiple jurisdictions within 24 hours")
  - `rule_template: dict | None` (JSONB) — auto-generated monitoring rule matching this typology
  - `jurisdictions: list[str]` — relevant jurisdictions
  - `source: TypologySource` — enum: `PLATFORM` (built-in), `COMMUNITY` (shared by tenant), `REGULATORY` (from AUSTRAC/FinCEN publications)
  - `contributed_by: str | None` — anonymised contributor identifier (not tenant name)
  - `status: str` — `DRAFT`, `UNDER_REVIEW`, `PUBLISHED`, `DEPRECATED`
  - `version: int`
  - `adopted_count: int = 0` — how many tenants have adopted this typology
  - `effectiveness_score: float | None` — based on how often adopted rules generate confirmed alerts
- `TenantTypologyAdoption` ORM model:
  - `tenant_id: str`
  - `typology_id: str` (FK)
  - `adopted_at: datetime`
  - `customised: bool` — whether the tenant modified the rule after adoption
  - `generated_rule_id: UUID | None` — FK to the tenant's monitoring rule created from this typology

**Why:** The typology model captures the abstract pattern without any tenant-specific data. The `indicators` list provides human-readable markers. The `rule_template` enables one-click conversion to a monitoring rule. Adoption tracking measures community value.

### Step 2: Implement Typology Contribution Pipeline

**Files:**
- `src/aml/services/typology/contribution.py`

**Implementation Details:**
- Implement `TypologyContributionService`:
  - `async contribute(tenant_id: str, typology: ContributeTypologyRequest) -> Typology`:
    - **Privacy validation**: scans the typology description and indicators for PII patterns (names, account numbers, addresses). Rejects if PII is detected.
    - Creates the typology in `DRAFT` status with an anonymised `contributed_by` identifier.
    - Optionally auto-generates a `rule_template` from the indicators using an LLM prompt.
  - `async review(typology_id: str, decision: str, reviewer_notes: str)`:
    - Platform moderator reviews and approves/rejects.
    - `PUBLISHED` typologies become visible in the community library.
  - `async deprecate(typology_id: str, reason: str)`:
    - Marks as `DEPRECATED`. Notifies tenants who adopted it.

**Why:** The contribution pipeline is the quality gate. Privacy validation ensures no tenant data leaks into the shared library. Moderation prevents low-quality or duplicate typologies.

### Step 3: Build Community Typology Library

**Files:**
- `src/aml/services/typology/library.py`

**Implementation Details:**
- Implement `TypologyLibrary`:
  - `async search(query: str | None, category: str | None, jurisdiction: str | None) -> list[Typology]`:
    - Full-text search across typology names, descriptions, and indicators.
    - Filterable by category, jurisdiction, risk level.
    - Sorted by adoption count (most popular first) or recency.
  - `async get_trending(limit: int = 10) -> list[Typology]`:
    - Returns recently published typologies with high adoption rates.
  - `async get_recommendations(tenant_id: str) -> list[Typology]`:
    - Recommends typologies based on the tenant's jurisdiction, industry type, and which typologies similar tenants have adopted (collaborative filtering, privacy-preserving).
  - `async get_effectiveness_stats() -> dict[str, float]`:
    - Aggregated effectiveness scores across all tenants (anonymised).

**Why:** The library is the community's value exchange. Search, recommendations, and trending make it easy for tenants to discover relevant patterns. Effectiveness tracking provides evidence-based adoption decisions.

### Step 4: Implement Typology-to-Rule Conversion

**Files:**
- `src/aml/services/typology/rule_converter.py`

**Implementation Details:**
- Implement `TypologyRuleConverter`:
  - `async convert_to_rule(typology: Typology, tenant_id: str) -> MonitoringRule`:
    - If the typology has a `rule_template`, uses it directly.
    - Otherwise, uses an LLM to convert the natural language indicators into structured rule conditions:
      - Prompt: "Convert these money laundering indicators into a structured monitoring rule with conditions (field, operator, value)."
      - Validates the generated conditions against the rule engine schema.
    - Creates the rule via `RuleManagementService.create_rule()` with `parent_template_id` set to the typology ID.
    - Optionally runs dry-run (BE-305) to preview impact before enabling.
  - Records the adoption in `TenantTypologyAdoption`.
  - Increments the typology's `adopted_count`.

**Why:** One-click conversion from typology to monitoring rule maximises the value of shared typologies. LLM-assisted conversion handles natural language indicators that don't map cleanly to structured rules.

### Step 5: Implement Privacy-Preserving Effectiveness Feedback

**Files:**
- `src/aml/services/typology/effectiveness.py`

**Implementation Details:**
- Implement `EffectivenessTracker`:
  - `async update_effectiveness(typology_id: str, tenant_id: str, confirmed_alerts: int, false_positives: int)`:
    - Called when a tenant's adopted rule (derived from a typology) generates alerts that are subsequently confirmed or cleared.
    - Stores anonymised counts — no details about which tenant or which transactions.
    - Computes `effectiveness_score = confirmed / (confirmed + false_positives)`.
  - Aggregation: scores are averaged across all adopting tenants.
  - Triggered automatically when an alert generated by a typology-derived rule is resolved.

**Why:** Effectiveness feedback creates a virtuous cycle: good typologies rise in rankings, poor ones are deprecated. Privacy-preserving aggregation ensures no tenant's alert data is exposed.

### Step 6: Ingest Regulatory Typologies from AUSTRAC/FinCEN

**Files:**
- `src/aml/services/typology/regulatory_ingest.py`
- `data/typologies/austrac_typologies.yaml`
- `data/typologies/fincen_advisories.yaml`

**Implementation Details:**
- Pre-built typologies from regulatory publications:
  - **AUSTRAC**: Money laundering through real estate, trade-based ML, structuring patterns, professional facilitators.
  - **FinCEN**: Advisories on human trafficking indicators, cyber-enabled crime, crypto mixing services.
- Implement `RegulatoryTypologyIngester`:
  - `seed_regulatory_typologies()`: loads from YAML files, creates typologies with `source: REGULATORY`, auto-publishes.
  - Also ingests the typology descriptions into the RAG pipeline for agent reference during investigations.
- Called during app startup.

**Why:** Regulatory typologies provide immediate value without community contributions. They also serve as examples for tenants considering contributing their own.

### Step 7: Create Typology API

**Files:**
- `src/aml/api/routers/typologies.py`

**Implementation Details:**
- `GET /api/v1/typologies` — Search/browse the community library. Query params: `query`, `category`, `jurisdiction`, `sort`.
- `GET /api/v1/typologies/trending` — Trending typologies.
- `GET /api/v1/typologies/recommended` — Recommendations for the tenant.
- `GET /api/v1/typologies/{id}` — Typology details including effectiveness stats.
- `POST /api/v1/typologies` — Contribute a new typology.
- `POST /api/v1/typologies/{id}/adopt` — Adopt a typology (creates a monitoring rule).
- `GET /api/v1/typologies/adopted` — List typologies the tenant has adopted.
- `POST /api/v1/typologies/{id}/review` — Moderate a contributed typology (platform admin).
- Register in `app.py`.

**Why:** The API supports both the future FE marketplace/gallery (FE-601) and programmatic typology management.

### Step 8: Implement Tests

**Files:**
- `tests/test_typology_sharing.py`

**Implementation Details:**
- Test contribution: submit a typology, verify it's in DRAFT status.
- Test PII rejection: submit a typology containing PII, verify it's rejected.
- Test adoption: adopt a typology, verify a monitoring rule is created.
- Test effectiveness: resolve alerts from an adopted rule, verify effectiveness score updates.
- Test privacy: verify no tenant-identifying information is accessible through the library API.
- Test regulatory ingest: verify AUSTRAC typologies are seeded on startup.
- Test search: verify full-text search returns relevant typologies.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **PII leakage in contributed typologies** | Critical | Automated PII scanning on contribution. Human review gate. |
| **Low-quality contributions** polluting the library | Medium | Review workflow. Effectiveness scoring surfaces quality. |
| **Typology gaming** (contributing patterns to create blind spots) | Low | Moderation. Effectiveness tracking exposes ineffective typologies. |
| **LLM-generated rule from indicators is incorrect** | Medium | Dry-run before enabling. Human review of generated rules. |
