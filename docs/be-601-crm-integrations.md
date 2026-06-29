# BE-601: CRM Integrations — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Tranche 2 entities (lawyers, accountants, real estate agents) run their businesses on CRMs and ERPs. Asking them to context-switch to a separate AML platform creates friction and reduces adoption. BE-601 builds **native CRM integrations** that embed AML compliance into the tools these businesses already use.

The integrations must:
1. **Pull** customer data from CRMs for automated KYC/CDD (BE-302).
2. **Push** risk scores, alert statuses, and compliance flags back to the CRM.
3. Support OAuth2 authentication for secure, delegated access.
4. Start with Xero (accounting), Salesforce (CRM), and MYOB (AU/NZ accounting).
5. Use a plugin architecture so new CRM connectors can be added without modifying core code.

### Dependencies on Existing Code
- `src/aml/db/models/customer.py` — `Customer` model (destination for pulled data).
- `src/aml/services/kyc/pipeline.py` (from BE-302) — CDD pipeline that processes imported customers.
- `src/aml/db/models/alert.py` — Alert model (status pushed back to CRM).
- `src/aml/core/config.py` — settings for CRM credentials.

---

## 2. Architecture Approach: Plugin-Based Bidirectional Sync

```
  CRM (Xero/SF/MYOB) ──> [Pull Adapter] ──> Customer Mapper ──> AML Platform ──> [Push Adapter] ──> CRM
                           (OAuth2 auth)      (normalize data)    (KYC/CDD,       (risk scores,
                                                                   monitoring)      alert status)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define CRM Integration Protocol

**Files:**
- `src/aml/services/integrations/protocol.py`

**Implementation Details:**
- Define `CRMIntegration` protocol:
  ```python
  class CRMIntegration(Protocol):
      provider_name: str  # "xero", "salesforce", "myob"

      async def authenticate(self, tenant_id: str, auth_code: str) -> OAuthTokens: ...
      async def pull_customers(self, tenant_id: str) -> list[CRMCustomer]: ...
      async def push_risk_score(self, tenant_id: str, external_id: str, score: int, flags: list[str]) -> bool: ...
      async def push_alert_status(self, tenant_id: str, external_id: str, alert_summary: dict) -> bool: ...
      async def webhook_handler(self, payload: dict) -> list[CRMEvent]: ...
  ```
- `CRMCustomer` normalised model:
  - `external_id`, `name`, `email`, `entity_type`, `jurisdiction`, `metadata` — maps to the platform's `Customer` model regardless of CRM source.
- `OAuthTokens`: `access_token`, `refresh_token`, `expires_at`, `scope`.

**Why:** The protocol ensures all CRM connectors follow the same interface. Any code that consumes CRM data works identically regardless of whether the data comes from Xero, Salesforce, or MYOB.

### Step 2: Implement OAuth2 Flow and Token Management

**Files:**
- `src/aml/services/integrations/oauth.py`
- `src/aml/db/models/integration.py`

**Implementation Details:**
- `TenantIntegration` ORM model:
  - `tenant_id: str` (FK)
  - `provider: str` — xero, salesforce, myob
  - `status: str` — `CONNECTED`, `DISCONNECTED`, `ERROR`
  - `access_token: str` (encrypted at rest)
  - `refresh_token: str` (encrypted at rest)
  - `token_expires_at: datetime`
  - `scopes: list[str]`
  - `last_sync_at: datetime | None`
  - `sync_config: dict | None` (JSONB) — sync frequency, field mappings
- Implement `OAuthManager`:
  - `get_auth_url(provider: str, tenant_id: str) -> str` — generates the OAuth2 authorization URL.
  - `exchange_code(provider: str, tenant_id: str, auth_code: str) -> OAuthTokens` — exchanges auth code for tokens.
  - `refresh_token(integration: TenantIntegration) -> OAuthTokens` — refreshes expired tokens.
  - `revoke(tenant_id: str, provider: str)` — disconnects the integration.
- Token encryption: encrypt tokens at rest using AES-256 with a key from environment variables.

**Why:** OAuth2 is the industry standard for CRM API access. Token management with automatic refresh ensures integrations don't silently break when tokens expire. Encryption protects credentials at rest.

### Step 3: Implement Xero Connector

**Files:**
- `src/aml/services/integrations/connectors/xero.py`

**Implementation Details:**
- Implement `XeroIntegration(CRMIntegration)`:
  - `authenticate()`: OAuth2 flow against Xero's identity endpoints.
  - `pull_customers()`:
    - Calls Xero Contacts API (`GET /api.xro/2.0/Contacts`).
    - Maps Xero contact fields to `CRMCustomer`: `ContactID` → `external_id`, `Name` → `name`, `EmailAddress` → `email`.
    - Handles pagination (Xero uses page-based).
  - `push_risk_score()`:
    - Updates a custom field on the Xero contact (or adds a note) with the AML risk score and flags.
  - `push_alert_status()`:
    - Adds a timeline note to the Xero contact with the alert summary.
  - `webhook_handler()`:
    - Processes Xero webhook events for contact updates (new customer, address change) to trigger re-screening.

**Why:** Xero is the dominant accounting platform for ANZ small-to-medium businesses. Tranche 2 accountants are a primary target market. Real-time webhook handling ensures compliance checks run automatically when customer data changes.

### Step 4: Implement Salesforce and MYOB Connectors (Stubs)

**Files:**
- `src/aml/services/integrations/connectors/salesforce.py`
- `src/aml/services/integrations/connectors/myob.py`

**Implementation Details:**
- `SalesforceIntegration(CRMIntegration)`:
  - OAuth2 via Salesforce Connected App.
  - Pull: SOQL query on Contact/Account objects.
  - Push: update custom fields or create a Task record.
  - Stub implementation with mock responses.
- `MYOBIntegration(CRMIntegration)`:
  - OAuth2 via MYOB Developer portal.
  - Pull: GET /Contact endpoint.
  - Push: update contact custom fields.
  - Stub implementation with mock responses.
- Both follow the same `CRMIntegration` protocol.

**Why:** Stubs establish the integration pattern and allow the API/UI to show these integrations as "coming soon." The Xero connector serves as the reference implementation.

### Step 5: Build Sync Engine

**Files:**
- `src/aml/services/integrations/sync.py`

**Implementation Details:**
- Implement `SyncEngine`:
  - `async full_sync(tenant_id: str, provider: str)`:
    - Pulls all customers from the CRM.
    - For each: upserts into the platform's `Customer` table (matching on `external_id`).
    - Triggers CDD pipeline (BE-302) for new customers.
    - Pushes current risk scores back to the CRM for existing customers.
  - `async incremental_sync(tenant_id: str, provider: str, since: datetime)`:
    - Pulls only changed customers since the last sync.
    - Processes changes (new customers → onboard, updated → re-screen).
  - `async push_updates(tenant_id: str, provider: str)`:
    - Pushes all pending risk score and alert status updates to the CRM.
  - Scheduled sync: runs on a configurable interval (default: every 4 hours).
  - Tracks sync state in `TenantIntegration.last_sync_at`.

**Why:** Full sync handles initial setup. Incremental sync handles ongoing changes efficiently. The push side ensures the CRM always reflects the latest compliance status.

### Step 6: Create Integration Management API

**Files:**
- `src/aml/api/routers/integrations.py`

**Implementation Details:**
- `GET /api/v1/integrations` — List available CRM providers and their connection status for the tenant.
- `GET /api/v1/integrations/{provider}/auth-url` — Get the OAuth2 authorization URL.
- `POST /api/v1/integrations/{provider}/callback` — OAuth2 callback (exchanges code for tokens).
- `POST /api/v1/integrations/{provider}/sync` — Trigger manual sync.
- `DELETE /api/v1/integrations/{provider}` — Disconnect integration.
- `GET /api/v1/integrations/{provider}/status` — Sync status, last sync time, error details.
- `POST /api/v1/integrations/{provider}/webhook` — Webhook receiver for CRM events.
- Register in `app.py`.

**Why:** These endpoints power the tenant configuration portal for managing CRM connections.

### Step 7: Implement Tests

**Files:**
- `tests/test_crm_integration.py`

**Implementation Details:**
- Test OAuth flow: mock Xero OAuth endpoints, verify token exchange and storage.
- Test customer pull: mock Xero API response, verify `CRMCustomer` mapping.
- Test sync engine: pull + upsert + KYC trigger workflow.
- Test push: verify risk score update calls the correct CRM API.
- Test webhook: simulate a Xero contact update event, verify re-screening is triggered.
- Test token refresh: expire a token, verify automatic refresh.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **CRM API breaking changes** | Medium | Pin API versions. Monitor CRM changelog. Adapter pattern isolates changes. |
| **Token leakage** | Critical | Encrypted at-rest storage. Tokens never logged. Short-lived access tokens. |
| **Sync conflicts** (data changed in both systems) | Medium | Last-write-wins with conflict logging. AML platform is authoritative for risk data. |
| **Rate limiting by CRM APIs** | Medium | Exponential backoff. Batch API calls where supported. Respect rate limit headers. |
