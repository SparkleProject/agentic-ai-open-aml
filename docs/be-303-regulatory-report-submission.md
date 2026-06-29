# BE-303: Regulatory Report Submission API — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

BE-301 generates draft SAR/SMR narratives. BE-303 handles the **last mile**: programmatic submission of approved reports to regulatory bodies. For the ANZ market, this means:
- **AUSTRAC** (Australia): SMR, TTR, and IFTI reports via AUSTRAC Online.
- **NZ FIU** (New Zealand): SAR reports via the goAML portal.

The submission API must:
1. Format approved reports into regulator-specific XML/JSON payloads.
2. Submit via the regulator's API or file-based upload gateway.
3. Track submission status, receipt references, and retry on failure.
4. Maintain an immutable audit trail of every submission attempt.

### Dependencies on Existing Code
- `src/aml/db/models/report.py` (created in BE-301) — `Report` model with `status`, `narrative`, `submission_reference`.
- `src/aml/services/reporting/narrative.py` (created in BE-301) — upstream narrative generation.
- `src/aml/core/config.py` — settings for regulator API credentials.

### Frontend Context
- `src/pages/SMRWorkspace.tsx` — "Submit to AUSTRAC" button currently calls a mock `setTimeout`. Must be wired to the real submission endpoint.

---

## 2. Architecture Approach: Adapter Pattern with Retry Queue

```
  Approved Report ──> Format Adapter ──> Submission Queue ──> Regulator Gateway ──> Receipt Tracking
                      (XML/JSON)         (Redis-backed)       (AUSTRAC / NZ FIU)    (DB + Audit Log)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Submission Adapter Protocol

**Files:**
- `src/aml/services/reporting/submission/protocol.py`

**Implementation Details:**
- Define `RegulatorySubmissionAdapter` protocol:
  ```python
  class RegulatorySubmissionAdapter(Protocol):
      async def format_payload(self, report: Report) -> bytes: ...
      async def submit(self, payload: bytes) -> SubmissionResult: ...
      async def check_status(self, reference: str) -> SubmissionStatus: ...
  ```
- `SubmissionResult`: `success: bool`, `reference: str | None`, `error: str | None`, `raw_response: dict`.
- `SubmissionStatus`: `status: str` (ACCEPTED, PROCESSING, REJECTED, UNKNOWN), `details: str`.

**Why:** Different regulators have entirely different submission formats and protocols. AUSTRAC uses XML over HTTPS; NZ FIU uses the goAML XML schema. The adapter pattern isolates these differences, mirroring the existing provider patterns throughout the codebase.

### Step 2: Implement AUSTRAC Submission Adapter

**Files:**
- `src/aml/services/reporting/submission/austrac.py`

**Implementation Details:**
- Implement `AUSTRACAdapter(RegulatorySubmissionAdapter)`:
  - `format_payload()`:
    - Maps `Report.narrative` sections to AUSTRAC XML schema fields.
    - SMR format: `<suspicious_matter_report>` with subject details, transaction details, suspicion basis, reporting entity.
    - TTR format: `<threshold_transaction_report>` with payer/payee, amount, transaction type.
    - IFTI format: `<international_funds_transfer>` with sender/receiver, correspondent banks, amount.
    - Validates the XML against the AUSTRAC XSD schema before submission.
  - `submit()`:
    - Posts the XML payload to the AUSTRAC Online API endpoint.
    - Handles authentication via AUSTRAC-issued API credentials (stored in `Settings`).
    - Returns the receipt reference on success.
  - `check_status()`:
    - Queries the AUSTRAC API for the submission status using the receipt reference.
- Initially implemented with a **mock mode** that validates the XML format but doesn't actually submit. Controlled by `Settings.austrac_mock_mode: bool = True`.

**Why:** AUSTRAC submission is the primary ANZ requirement. Mock mode allows full end-to-end testing of the pipeline without AUSTRAC API access during development. XML schema validation catches formatting errors before they reach the regulator.

### Step 3: Implement NZ FIU Submission Adapter

**Files:**
- `src/aml/services/reporting/submission/nz_fiu.py`

**Implementation Details:**
- Implement `NZFIUAdapter(RegulatorySubmissionAdapter)`:
  - `format_payload()`:
    - Maps to the goAML XML schema used by the NZ FIU.
    - SAR format includes: reporting entity, subject, transaction details, reason for suspicion.
  - `submit()`:
    - Posts to the NZ FIU goAML endpoint.
    - Handles authentication (OAuth2 client credentials flow).
  - `check_status()`:
    - Queries submission status.
- Also starts in **mock mode**.

**Why:** NZ is a primary market alongside Australia. The goAML schema differs from AUSTRAC's proprietary format, justifying a separate adapter.

### Step 4: Build Submission Service with Retry Logic

**Files:**
- `src/aml/services/reporting/submission/service.py`

**Implementation Details:**
- Implement `ReportSubmissionService`:
  - `async submit_report(report_id: UUID, tenant_id: str) -> SubmissionResult`:
    - Validates the report is in `APPROVED` status.
    - Selects the appropriate adapter based on `report.report_type` (AUSTRAC_SMR → AUSTRACAdapter, NZ_SAR → NZFIUAdapter).
    - Formats the payload.
    - Attempts submission.
    - On success: updates `report.status = SUBMITTED`, stores `submission_reference` and `submitted_at`.
    - On failure: increments retry count, schedules retry with exponential backoff (1m, 5m, 15m, 1h).
    - After max retries (configurable, default 5): marks report as `SUBMISSION_FAILED`, creates an alert for manual intervention.
  - `async check_submission_status(report_id: UUID) -> SubmissionStatus`:
    - Calls the adapter's `check_status()` with the stored reference.
  - Records every submission attempt in a `submission_audit_log` table.
- `SubmissionAuditLog` model:
  - `report_id`, `attempt_number`, `timestamp`, `status`, `response_payload`, `error_message`.

**Why:** Regulator APIs can be unreliable. Retry logic with exponential backoff is essential for production. The audit log satisfies regulatory requirements for proving submission attempts and their outcomes.

### Step 5: Create Submission API Endpoints

**Files:**
- `src/aml/api/routers/reports.py` (update from BE-301)

**Implementation Details:**
- Add to existing reports router:
  - `POST /api/v1/reports/{report_id}/submit` — Triggers submission for an approved report.
    - Validates RBAC: only `compliance_officer` or `admin` roles can submit.
    - Returns the submission result with receipt reference.
  - `GET /api/v1/reports/{report_id}/submission-status` — Checks current submission status with the regulator.
  - `GET /api/v1/reports/{report_id}/submission-history` — Returns the full audit log of submission attempts.

**Why:** The FE SMRWorkspace's "Submit to AUSTRAC" button needs a single POST endpoint. The status and history endpoints support monitoring and troubleshooting failed submissions.

### Step 6: Add Configuration Settings

**Files:**
- `src/aml/core/config.py` (update)

**Implementation Details:**
- Add to `Settings`:
  - `austrac_api_url: str | None = None`
  - `austrac_api_key: str | None = None`
  - `austrac_mock_mode: bool = True`
  - `nz_fiu_api_url: str | None = None`
  - `nz_fiu_client_id: str | None = None`
  - `nz_fiu_client_secret: str | None = None`
  - `nz_fiu_mock_mode: bool = True`
  - `submission_max_retries: int = 5`

**Why:** Regulator credentials must be configurable via environment variables, never hardcoded. Mock mode defaults allow the platform to function without real credentials during development.

### Step 7: Implement Tests

**Files:**
- `tests/test_report_submission.py`

**Implementation Details:**
- Test XML payload formatting against AUSTRAC and NZ FIU schemas.
- Test retry logic: mock a failing adapter, verify exponential backoff and max retry limit.
- Test audit logging: verify every attempt is recorded.
- Test status transitions: APPROVED → SUBMITTED, APPROVED → SUBMISSION_FAILED.
- Test RBAC: verify non-authorized users cannot trigger submission.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **AUSTRAC API format changes** | High | XSD validation catches mismatches. Template-based XML generation. Monitor AUSTRAC release notes. |
| **Credential leakage** | Critical | Environment variable injection only. Never stored in DB or logs. |
| **Submission rejected by regulator** | Medium | Detailed error parsing from regulator response. Alert created for compliance team. |
| **Duplicate submissions** | High (regulatory violation) | Idempotency check: verify no existing `SUBMITTED` record for the same case + report_type. |
