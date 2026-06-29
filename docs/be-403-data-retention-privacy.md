# BE-403: Data Retention & Privacy — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

The platform handles highly sensitive personal and financial data across multiple jurisdictions with different retention requirements:
- **AUSTRAC (AU)**: 7-year retention for customer records and transaction data.
- **NZ Privacy Act 2020**: Data minimisation principle — retain only what is necessary.
- **GDPR** (for future EU expansion): Right to erasure, data portability, consent management.
- **Australian Privacy Act 1988**: APP 11 — destroy or de-identify personal information no longer needed.

BE-403 implements **configurable data retention and privacy controls** including automated TTL-based deletion, soft-delete with scheduled hard-delete, tenant-level retention policies, and right-to-deletion support.

### Dependencies on Existing Code
- `src/aml/db/base.py` — `Base` model with `created_at`, `updated_at`.
- `src/aml/db/models/` — all models that store PII (customer, transaction, alert, case, report, CDD record).
- `src/aml/core/config.py` — settings for retention policies.
- `src/aml/db/models/tenant.py` — `Tenant.settings` for per-tenant configuration.

---

## 2. Architecture Approach: Policy-Driven Lifecycle Management

```
  Data Creation ──> TTL Assignment ──> Soft Delete (on expiry) ──> Hard Delete (after grace period)
                         │                     │                         │
                   Retention Policy        Tombstone Record          Secure Erasure
                   (tenant-scoped)         (audit proof)            (overwrite + vacuum)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Retention Policy Models

**Files:**
- `src/aml/services/privacy/retention.py`

**Implementation Details:**
- Define `RetentionPolicy` model:
  - `entity_type: str` — which model this applies to (customer, transaction, alert, case, report, cdd_record, governance_log).
  - `retention_days: int` — how long to keep the data (e.g., 2555 for 7 years).
  - `grace_period_days: int` — soft-delete → hard-delete delay (default 30 days).
  - `jurisdiction: str` — which legal framework this policy satisfies.
  - `legal_basis: str` — regulatory citation (e.g., "AUSTRAC AML/CTF Act s.107").
- Define `DefaultRetentionPolicies` — built-in policies per jurisdiction:
  - AU: 7 years for transactions, customers, reports. 5 years for cases and alerts.
  - NZ: 5 years for transactions and customers. 7 years for SAR-related data.
- Tenants can override defaults via `tenant.settings["retention_policies"]`.

**Why:** Different data types have different legal retention requirements. A tenant in both AU and NZ needs the most restrictive policy for shared data and jurisdiction-specific policies for reporting data. The policy model makes this configurable without code changes.

### Step 2: Add Soft-Delete Infrastructure to Models

**Files:**
- `src/aml/db/base.py` (update)
- `src/aml/db/models/customer.py` (update)
- `src/aml/db/models/transaction.py` (update)

**Implementation Details:**
- Add `SoftDeleteMixin` to `base.py`:
  - `deleted_at: datetime | None` — null = active, set = soft-deleted.
  - `deleted_by: str | None` — user/system that triggered deletion.
  - `deletion_reason: str | None` — regulatory, user_request, retention_expiry.
  - `hard_delete_scheduled_at: datetime | None` — when the hard delete will occur.
- Apply `SoftDeleteMixin` to: `Customer`, `Transaction`, `Alert`, `Case`, `Report`, `CDDRecord`.
- Add a global query filter helper that excludes soft-deleted records by default:
  - `active_only(query)` — adds `WHERE deleted_at IS NULL`.
- Update existing CRUD queries to use `active_only()`.

**Why:** Soft-delete ensures data is immediately hidden from the application but remains recoverable during the grace period. This is essential for handling accidental deletions and regulatory requests that may be reversed.

### Step 3: Implement Retention Enforcement Service

**Files:**
- `src/aml/services/privacy/enforcement.py`

**Implementation Details:**
- Implement `RetentionEnforcementService`:
  - `async enforce_policies(tenant_id: str | None = None)`:
    - Loads retention policies for the tenant (or all tenants if not specified).
    - For each entity type, queries for records where `created_at + retention_days < now()` and `deleted_at IS NULL`.
    - Soft-deletes matching records with `deletion_reason = "retention_expiry"`.
    - Sets `hard_delete_scheduled_at = now() + grace_period_days`.
  - `async execute_hard_deletes()`:
    - Queries for records where `hard_delete_scheduled_at < now()`.
    - For each record:
      1. Creates a `DeletionTombstone` (proof that data existed and was lawfully deleted).
      2. Permanently deletes the record from the database.
      3. Deletes associated vector embeddings from Milvus.
      4. Logs the deletion in the governance log (BE-402).
  - Both methods are idempotent — safe to run multiple times.
- `DeletionTombstone` model:
  - `entity_type`, `entity_id`, `tenant_id`, `deleted_at`, `deletion_reason`, `legal_basis`, `content_hash` (hash of the deleted data for proof).

**Why:** Automated enforcement ensures retention policies are applied consistently without human intervention. Tombstones prove to regulators that data was held for the required period and then lawfully destroyed. The grace period protects against premature deletion.

### Step 4: Implement Right-to-Deletion Handler

**Files:**
- `src/aml/services/privacy/deletion_request.py`

**Implementation Details:**
- Implement `DeletionRequestService`:
  - `async request_deletion(customer_id: UUID, tenant_id: str, requested_by: str) -> DeletionRequest`:
    - Creates a `DeletionRequest` record tracking the request.
    - Checks legal holds: if the customer is involved in an active case or a filed SAR, deletion is **blocked** (legal obligation to retain overrides right to deletion).
    - If no holds, initiates soft-delete cascade:
      - Soft-deletes the `Customer` record.
      - Soft-deletes all associated `Transaction` records.
      - Soft-deletes associated `CDDRecord`s.
      - De-identifies (rather than deletes) `Alert` and `Case` records that reference this customer (replace PII with `[REDACTED]`).
    - Returns the request with status: `COMPLETED`, `BLOCKED_LEGAL_HOLD`, `PARTIAL`.
  - `DeletionRequest` model:
    - `customer_id`, `tenant_id`, `requested_by`, `requested_at`, `status`, `legal_hold_reason`, `completed_at`, `records_affected: int`.

**Why:** Right-to-deletion is a legal requirement under GDPR and NZ Privacy Act. However, AML regulations create a conflict: you cannot delete a customer involved in a suspicious activity investigation. The service resolves this conflict by checking legal holds before proceeding.

### Step 5: Create Privacy API Router

**Files:**
- `src/aml/api/routers/privacy.py`

**Implementation Details:**
- `GET /api/v1/privacy/retention-policies` — Lists active retention policies for the tenant.
- `PUT /api/v1/privacy/retention-policies` — Updates tenant-specific retention overrides.
- `POST /api/v1/privacy/deletion-requests` — Submits a customer data deletion request.
  - Body: `{ "customer_id": "...", "reason": "..." }`.
  - Returns status (completed, blocked, partial) with explanation.
- `GET /api/v1/privacy/deletion-requests` — Lists all deletion requests with their status.
- `GET /api/v1/privacy/retention-report` — Generates a report of data retention status across all entity types (counts by age bracket).
- Register in `app.py`.

**Why:** The API enables the FE configuration portal to manage retention policies and provides a programmatic interface for handling deletion requests.

### Step 6: Schedule Retention Jobs

**Files:**
- `src/aml/app.py` (update)

**Implementation Details:**
- In the `lifespan` startup, schedule two periodic background tasks:
  - **Retention enforcement**: runs daily at 02:00 UTC. Calls `enforce_policies()` for all tenants.
  - **Hard delete execution**: runs daily at 03:00 UTC. Calls `execute_hard_deletes()`.
- Both jobs log their execution in the governance log.
- Add health check endpoint for retention job status: last run time, records affected, errors.

**Why:** Retention enforcement must be automated and reliable. Running during off-peak hours minimises performance impact. Governance logging provides an audit trail for when retention was applied.

### Step 7: Implement Tests

**Files:**
- `tests/test_data_retention.py`
- `tests/test_deletion_request.py`

**Implementation Details:**
- Test policy application: create records with old `created_at`, run enforcement, verify soft-delete.
- Test grace period: verify hard-delete only occurs after grace period expires.
- Test tombstone creation: verify tombstones contain correct hashes and metadata.
- Test deletion request: customer with no legal hold → successful deletion cascade.
- Test legal hold block: customer involved in active case → deletion blocked.
- Test de-identification: verify PII is replaced in linked alerts and cases.
- Test idempotency: run enforcement twice, verify no duplicate actions.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Premature deletion of legally required data** | Critical | Legal hold check before any deletion. Conservative grace periods. |
| **Retention enforcement job failure** | High | Alerting on job failures. Idempotent design allows safe re-run. |
| **Orphaned vector embeddings** after hard delete | Medium | Hard delete service also cleans Milvus. Periodic reconciliation job. |
| **Conflicting retention requirements** across jurisdictions | Medium | Use the most restrictive policy when a customer spans multiple jurisdictions. |
