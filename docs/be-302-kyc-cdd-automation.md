# BE-302: KYC/CDD Automation Pipeline — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Tranche 2 entities (lawyers, accountants, real estate agents) face AML obligations starting 1 July 2026. Unlike banks, they lack existing KYC infrastructure. BE-302 builds an **automated KYC/CDD pipeline** that handles customer onboarding, identity verification, risk scoring, and ongoing due diligence.

The pipeline must:
1. Orchestrate multi-step onboarding: ID verification → PEP screening → sanctions check → adverse media scan → risk scoring.
2. Integrate with ANZ identity verification services (GreenID, FrankieOne) via adapters.
3. Calculate dynamic risk scores based on multiple weighted factors.
4. Support both initial CDD and ongoing/enhanced due diligence (EDD).
5. Target 70% full automation — only edge cases escalate to human review.

### Dependencies on Existing Code
- `src/aml/db/models/customer.py` — `Customer` model with `risk_rating`, `customer_type`, `metadata_`.
- `src/aml/agents/tools/local/screening.py` — `SanctionsTool`, `PEPScreeningTool` (mock implementations, will be extended).
- `src/aml/agents/specialized/base.py` — `CDDAgent` definition (currently limited to `TransactionLookupTool`).
- `src/aml/services/rag/service.py` — RAG for retrieving tenant-specific CDD policies.

### Frontend Context
- `src/pages/KYCDashboard.tsx` and `src/pages/KYCDetail.tsx` — FE already has KYC UI components using `mockKYCData.ts`. The backend API must match the data shapes expected by these pages: `KYCCustomer`, onboarding stages, risk breakdowns, and verification statuses.

---

## 2. Architecture Approach: Pipeline Orchestrator with Pluggable Verification Adapters

```
  Customer Data ──> Onboarding Pipeline ──> ID Verify ──> PEP/Sanctions ──> Adverse Media ──> Risk Score ──> Decision
       │                                       │              │                  │                │
       │                                  GreenID/          Existing          OSINT/News       Weighted
       │                                  FrankieOne        BE-203 Tools     API Adapter       Scoring
       │                                  Adapter
       └──────────────────────────────────────────────────────────────────────────────────────> CDD Record (DB)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define CDD Data Models

**Files:**
- `src/aml/db/models/cdd_record.py`

**Implementation Details:**
- Define `CDDRecord` ORM model extending `TenantMixin, Base`:
  - `customer_id: UUID` (FK to `customers.id`)
  - `cdd_type: CDDType` — enum: `INITIAL`, `ONGOING`, `ENHANCED`
  - `status: CDDStatus` — enum: `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED`, `ESCALATED`
  - `onboarding_stage: str` — tracks current stage: `ID_VERIFICATION`, `PEP_SCREENING`, `SANCTIONS_CHECK`, `ADVERSE_MEDIA`, `RISK_SCORING`, `COMPLETE`
  - `id_verification: dict | None` (JSONB) — result from identity verification provider
  - `pep_result: dict | None` (JSONB) — PEP screening result
  - `sanctions_result: dict | None` (JSONB) — sanctions check result
  - `adverse_media_result: dict | None` (JSONB) — adverse media scan result
  - `risk_assessment: dict | None` (JSONB) — final risk breakdown with factor weights
  - `overall_risk_score: int` (0-100)
  - `decision: str | None` — `APPROVED`, `REJECTED`, `MANUAL_REVIEW`
  - `reviewed_by: str | None`
  - `next_review_date: datetime | None`
- Add relationship on `Customer`: `cdd_records: Mapped[list["CDDRecord"]]`.

**Why:** CDD records need a separate model from `Customer` because each customer can have multiple CDD assessments over time (initial, periodic reviews, triggered enhanced DD). The JSONB fields store provider-specific responses without requiring rigid schemas per provider.

### Step 2: Implement Identity Verification Adapter Interface

**Files:**
- `src/aml/services/kyc/protocol.py`
- `src/aml/services/kyc/adapters/mock.py`
- `src/aml/services/kyc/adapters/frankie_one.py` (stub)

**Implementation Details:**
- Define `IdentityVerificationProvider` protocol:
  - `async verify_identity(customer: Customer, documents: list[dict]) -> VerificationResult`
  - `VerificationResult`: `verified: bool`, `confidence: float`, `checks: list[CheckResult]`, `provider_ref: str`
- Implement `MockIdentityVerifier` for development/testing.
- Implement `FrankieOneAdapter` as a stub (ready for API key integration):
  - Uses `httpx.AsyncClient` to call FrankieOne's REST API.
  - Maps the response to `VerificationResult`.
- Factory function: `get_identity_verifier(settings) -> IdentityVerificationProvider`.

**Why:** Identity verification providers vary by jurisdiction and tenant preference. The adapter pattern (mirroring `src/aml/services/llm/protocol.py`) makes it trivial to swap GreenID for FrankieOne or add a new provider without changing the pipeline logic.

### Step 3: Implement Risk Scoring Engine

**Files:**
- `src/aml/services/kyc/risk_scoring.py`

**Implementation Details:**
- Implement `RiskScoringEngine`:
  - `calculate_risk(customer: Customer, cdd: CDDRecord, tenant_config: dict) -> RiskAssessment`
  - Weighted factor scoring:
    - **Customer type risk** (30%): entity type (trust, partnership, sole trader), jurisdiction.
    - **PEP status** (25%): direct PEP, PEP associate, RCA (Relative or Close Associate).
    - **Sanctions proximity** (20%): direct match, related entity match, jurisdiction risk.
    - **Adverse media** (15%): severity of findings, recency, relevance.
    - **Transaction profile** (10%): historical pattern anomalies.
  - Weights are configurable per tenant via `tenant.settings["risk_weights"]`.
  - Output `RiskAssessment`: `overall_score: int`, `risk_level: RiskRating`, `factor_breakdown: dict[str, FactorScore]`, `auto_decision: str`.
  - Auto-decision rules:
    - Score < 30: `APPROVED` (auto-onboard)
    - Score 30-70: `MANUAL_REVIEW`
    - Score > 70: `REJECTED` (or `ENHANCED_DD_REQUIRED`)

**Why:** A transparent, weighted scoring model is essential for regulatory audit. Regulators need to see why a customer was rated HIGH vs. LOW. The configurable weights allow tenants to adjust their risk appetite within regulatory bounds.

### Step 4: Build the CDD Pipeline Orchestrator

**Files:**
- `src/aml/services/kyc/pipeline.py`

**Implementation Details:**
- Implement `CDDPipeline`:
  - `async run_onboarding(customer: Customer, tenant_id: str, cdd_type: CDDType = CDDType.INITIAL) -> CDDRecord`
  - Creates a `CDDRecord` in `PENDING` status.
  - Executes stages sequentially, updating `onboarding_stage` after each:
    1. **ID Verification**: Calls `IdentityVerificationProvider.verify_identity()`.
    2. **PEP Screening**: Calls `PEPScreeningTool.execute()` via the ToolRegistry.
    3. **Sanctions Check**: Calls `SanctionsTool.execute()` via the ToolRegistry.
    4. **Adverse Media**: Calls a new `AdverseMediaTool` (OSINT adapter).
    5. **Risk Scoring**: Calls `RiskScoringEngine.calculate_risk()`.
  - If any stage fails, marks the CDD as `FAILED` with error details.
  - If the overall risk score triggers `MANUAL_REVIEW`, sets status to `ESCALATED`.
  - Otherwise, updates the `Customer.risk_rating` and completes.
  - `async run_periodic_review(customer: Customer, tenant_id: str) -> CDDRecord` — re-runs PEP/sanctions/adverse media checks and recalculates risk.

**Why:** The pipeline orchestrator is the heart of BE-302. Sequential execution ensures each check has the results of prior checks available (e.g., a PEP hit informs the risk score). Stage-by-stage progress tracking maps directly to the `OnboardingProgress` FE component.

### Step 5: Create KYC API Router

**Files:**
- `src/aml/api/routers/kyc.py`

**Implementation Details:**
- `POST /api/v1/kyc/onboard` — Initiates CDD pipeline for a customer. Body: `{ "customer_id": "...", "documents": [...] }`.
- `GET /api/v1/kyc/customers` — Lists customers with their latest CDD status, risk score, and onboarding stage. Supports filtering by risk level, status, and tranche.
- `GET /api/v1/kyc/customers/{customer_id}` — Detailed CDD view: all CDD records, risk breakdowns, verification results.
- `POST /api/v1/kyc/customers/{customer_id}/review` — Triggers periodic review (re-runs CDD pipeline with `ONGOING` type).
- `POST /api/v1/kyc/customers/{customer_id}/escalate` — Manually escalates to enhanced due diligence.
- Register in `app.py`.

**Why:** These endpoints map directly to the FE `KYCDashboard.tsx` and `KYCDetail.tsx` pages, which currently use `mockKYCData.ts`. The response shapes (`KYCCustomer` with `onboardingStage`, `overallRiskLevel`, `onboardingProgress`) must match the FE types.

### Step 6: Implement Adverse Media Tool

**Files:**
- `src/aml/agents/tools/local/adverse_media.py`

**Implementation Details:**
- Implement `AdverseMediaTool` extending `BaseTool`:
  - Input: `{ "entity_name": "...", "jurisdiction": "..." }`
  - Initially a mock returning configurable results.
  - Designed for future integration with OSINT APIs (e.g., Dow Jones, Refinitiv World-Check, or open-source news APIs).
  - Output: list of media findings with `source`, `headline`, `date`, `severity`, `relevance_score`.
- Register in the `ToolRegistry` during app startup.
- Add to `CDDAgent.tool_whitelist`.

**Why:** Adverse media scanning is a required CDD step under AUSTRAC guidelines. The mock implementation allows the pipeline to function end-to-end while the external API integration is completed in a future iteration.

### Step 7: Implement Tests

**Files:**
- `tests/test_kyc_pipeline.py`
- `tests/test_risk_scoring.py`

**Implementation Details:**
- Test the full onboarding pipeline with mocked providers: verify stage progression, status updates, risk calculation.
- Test risk scoring with various factor combinations: verify score ranges and auto-decisions.
- Test tenant-specific weight configuration.
- Test periodic review: verify it creates a new CDD record without duplicating the customer.
- API integration tests: onboard → review → escalate workflow.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **ID verification provider downtime** | High (blocks onboarding) | Adapter pattern enables failover. Queue failed verifications for retry. |
| **Risk score gaming** by adjusting weights | Medium (regulatory risk) | Audit log on weight changes. Minimum weight floors enforced by validation. |
| **PII exposure in CDD records** | Critical | Encrypt JSONB fields at rest. RBAC restricts access to CDD detail endpoints (Phase 4 BE-404). |
| **70% automation target not met** | Medium (operational cost) | Iterative threshold tuning. RAG-enriched risk scoring improves accuracy over time. |
