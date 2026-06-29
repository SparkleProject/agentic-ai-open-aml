# BE-602: Multi-Jurisdiction Regulatory Module — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Phase 3 (BE-301, BE-303) builds AUSTRAC and NZ FIU reporting. BE-602 extends the platform to support **multiple regulatory jurisdictions** without duplicating the core investigation engine. The same agentic core investigates alerts identically, but the final reporting layer adapts to the local regulator's format, thresholds, and submission requirements.

Target jurisdictions (in priority order):
1. **AUSTRAC** (Australia) — already implemented in Phase 3.
2. **NZ FIU** (New Zealand) — already implemented in Phase 3.
3. **FinCEN** (United States) — SAR and CTR formats.
4. **FCA** (United Kingdom) — SAR format for NCA.

### Dependencies on Existing Code
- `src/aml/services/reporting/templates.py` (from BE-301) — `ReportTemplate`, `TemplateRegistry`.
- `src/aml/services/reporting/submission/protocol.py` (from BE-303) — `RegulatorySubmissionAdapter`.
- `src/aml/services/reporting/narrative.py` (from BE-301) — `NarrativeGenerationService`.
- `src/aml/services/monitoring/rules.py` (from BE-206/BE-305) — monitoring rules vary by jurisdiction.

---

## 2. Architecture Approach: Pluggable Regulatory Adapters

```
  Core Investigation ──> Jurisdiction Resolver ──> Reporting Adapter ──> Submission Adapter
  (same for all)          (tenant locale)          (SAR/SMR/CTR format)  (regulator gateway)
                                                        │
                                               Template + Thresholds
                                               (per jurisdiction)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Jurisdiction Configuration Model

**Files:**
- `src/aml/services/regulatory/jurisdiction.py`

**Implementation Details:**
- Define `JurisdictionConfig` model:
  - `code: str` — ISO country code (AU, NZ, US, GB)
  - `regulator: str` — AUSTRAC, NZ_FIU, FINCEN, FCA
  - `report_types: list[str]` — supported report types (SMR, TTR, IFTI, SAR, CTR)
  - `currency: str` — default currency (AUD, NZD, USD, GBP)
  - `thresholds: dict[str, float]`:
    - `reporting_threshold`: cash transaction reporting threshold (AU: $10,000, US: $10,000, NZ: no fixed threshold)
    - `structuring_window_hours`: time window for structuring detection
    - `pep_check_required: bool`
  - `regulatory_guidance_docs: list[str]` — paths to RAG-ingestible regulatory documents
  - `submission_adapter: str` — which adapter class to use
- `JurisdictionRegistry`:
  - `get_config(code: str) -> JurisdictionConfig`
  - `get_for_tenant(tenant_id: str) -> JurisdictionConfig` — resolves from `tenant.settings["jurisdiction"]`
  - `list_supported() -> list[str]`
- Ship with built-in configs for AU, NZ. Stub configs for US, GB.

**Why:** Centralising jurisdiction-specific values in one configuration prevents scattered if/else blocks throughout the codebase. The registry pattern is consistent with `AgentRegistry`, `ToolRegistry`, and `TemplateRegistry`.

### Step 2: Implement FinCEN Reporting Adapter

**Files:**
- `src/aml/services/reporting/submission/fincen.py`
- `data/report_templates/fincen_sar.yaml`
- `data/report_templates/fincen_ctr.yaml`

**Implementation Details:**
- Create FinCEN report templates:
  - **SAR template**: Filing Information, Subject Information, Suspicious Activity Information, Narrative.
  - **CTR template** (Currency Transaction Report): Transaction Information, Person Involved, Amount Details.
- Implement `FinCENAdapter(RegulatorySubmissionAdapter)`:
  - `format_payload()`:
    - Maps narrative sections to FinCEN BSA E-Filing XML schema.
    - SAR: populates Form 111 fields.
    - CTR: populates Form 112 fields.
  - `submit()`:
    - Posts to FinCEN's BSA E-Filing System.
    - Handles FinCEN batch file upload format.
  - `check_status()`:
    - Queries submission acknowledgment status.
  - Starts in **mock mode**.

**Why:** US expansion is a logical next market. FinCEN's BSA E-Filing has well-documented XML schemas. The adapter isolates all US-specific formatting.

### Step 3: Implement FCA/NCA Reporting Adapter

**Files:**
- `src/aml/services/reporting/submission/fca.py`
- `data/report_templates/fca_sar.yaml`

**Implementation Details:**
- Create FCA SAR template:
  - Sections: Discloser Details, Subject Details, Reason for Suspicion, Transaction Details.
- Implement `FCAAdapter(RegulatorySubmissionAdapter)`:
  - `format_payload()`: Maps to NCA SAR Online format.
  - `submit()`: Posts to NCA's SAR Online system.
  - `check_status()`: Queries acknowledgment.
  - Starts in **mock mode**.

**Why:** UK financial services represent a large addressable market. The FCA/NCA SAR format differs significantly from FinCEN and AUSTRAC, justifying a separate adapter.

### Step 4: Implement Jurisdiction-Aware Narrative Generation

**Files:**
- `src/aml/services/reporting/narrative.py` (update from BE-301)

**Implementation Details:**
- Update `NarrativeGenerationService.generate_draft()`:
  - Accept `jurisdiction: str` parameter.
  - Load jurisdiction-specific regulatory guidance from RAG:
    - AU: AUSTRAC typology guides.
    - NZ: NZ FIU guidelines.
    - US: FinCEN SAR filing instructions.
    - GB: FCA/NCA SAR guidance.
  - Adjust the LLM system prompt to include jurisdiction-specific language requirements:
    - US: use "Suspicious Activity Report" terminology, reference Bank Secrecy Act.
    - AU: use "Suspicious Matter Report" terminology, reference AML/CTF Act.
    - NZ: use "Suspicious Activity Report" terminology, reference Anti-Money Laundering and Countering Financing of Terrorism Act 2009.
    - GB: use "Suspicious Activity Report" terminology, reference Proceeds of Crime Act 2002.
  - Select the correct report template based on jurisdiction + report type.

**Why:** Regulatory narratives must use jurisdiction-correct terminology and legal references. An AUSTRAC SMR that references "Bank Secrecy Act" would be flagged by the regulator.

### Step 5: Implement Jurisdiction-Aware Monitoring Rules

**Files:**
- `src/aml/services/monitoring/rules.py` (update)
- `src/aml/services/monitoring/default_templates.py` (update from BE-305)

**Implementation Details:**
- Update `RuleEngine.load_rules()` to include jurisdiction as a filter.
- Add jurisdiction-specific default rule templates:
  - **US (FinCEN)**: CTR filing for cash transactions ≥$10,000. SAR filing for suspicious patterns ≥$5,000. Structuring detection ($5,000-$9,999 range).
  - **UK (FCA)**: No fixed threshold for SAR. Consent SAR for transactions requiring NCA consent. Terrorism-related reporting.
- Tenants adopting a jurisdiction automatically get the relevant default rule templates.

**Why:** Monitoring thresholds are jurisdiction-specific. US $10,000 cash reporting differs from AU's $10,000 threshold in currency, scope, and applicability. Rules must be jurisdiction-aware to generate correct alert types.

### Step 6: Create Multi-Jurisdiction API and Tenant Configuration

**Files:**
- `src/aml/api/routers/regulatory.py`

**Implementation Details:**
- `GET /api/v1/regulatory/jurisdictions` — List supported jurisdictions with capabilities.
- `GET /api/v1/regulatory/jurisdictions/{code}` — Jurisdiction details (thresholds, report types, adapter status).
- `PUT /api/v1/tenants/{tenant_id}/jurisdiction` — Set/change tenant's primary jurisdiction.
- `GET /api/v1/regulatory/report-types` — Available report types for the tenant's jurisdiction.
- Register in `app.py`.

**Why:** Tenants need to select their jurisdiction during onboarding. The API surfaces which report types and monitoring rules are available for their jurisdiction.

### Step 7: Implement Tests

**Files:**
- `tests/test_multi_jurisdiction.py`

**Implementation Details:**
- Test jurisdiction resolution: tenant with `jurisdiction: "AU"` → AUSTRAC adapter.
- Test FinCEN payload formatting: verify XML matches BSA E-Filing schema.
- Test jurisdiction-specific narrative: AU narrative uses "SMR", US narrative uses "SAR".
- Test threshold application: US rules trigger at $10,000 USD, AU rules trigger at $10,000 AUD.
- Test tenant jurisdiction switch: change from AU to US, verify rules and templates update.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Regulatory format changes** per jurisdiction | High | YAML templates updateable without code. Monitor regulatory bulletins. |
| **Incorrect regulatory language** in narratives | Critical | Jurisdiction-specific RAG guidance. Chain of Verification (BE-301). Human review mandatory. |
| **Threshold differences causing missed filings** | Critical | Jurisdiction-specific default rules. Validation that tenants have required rules enabled. |
| **Multi-jurisdiction tenants** (operating in multiple countries) | Medium | Support multiple jurisdictions per tenant. Route reports based on transaction jurisdiction, not tenant home jurisdiction. |
