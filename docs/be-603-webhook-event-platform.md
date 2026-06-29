# BE-603: Webhook & Event Platform — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Enterprise clients need to integrate the AML platform with their existing systems: SIEM tools, case management systems, compliance dashboards, and notification services. BE-603 builds a **webhook and event platform** that fires notifications on key state changes and allows external systems to subscribe.

The platform must:
1. Emit events for key state changes: alert created, case opened, investigation completed, SAR submitted.
2. Allow tenants to register webhook URLs with event type filters.
3. Provide reliable delivery with retry, dead-letter queue, and signature verification.
4. Support event replay for missed webhooks (e.g., after an outage).

### Dependencies on Existing Code
- `src/aml/db/models/alert.py` — Alert lifecycle events.
- `src/aml/db/models/case.py` — Case lifecycle events.
- `src/aml/db/models/report.py` (from BE-301) — Report lifecycle events.
- `src/aml/core/config.py` — settings for webhook infrastructure.

---

## 2. Architecture Approach: Event Bus with Webhook Dispatch

```
  State Change ──> Event Bus (in-process) ──> Webhook Dispatcher ──> HTTP POST to subscriber
       │                                            │                       │
  alert.created                               Retry Queue             Signature Verification
  case.closed                                (Redis-backed)           (HMAC-SHA256)
  sar.submitted
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Event Types and Event Bus

**Files:**
- `src/aml/services/events/bus.py`
- `src/aml/services/events/types.py`

**Implementation Details:**
- Define event type constants:
  ```python
  class EventType(StrEnum):
      ALERT_CREATED = "alert.created"
      ALERT_UPDATED = "alert.updated"
      ALERT_RESOLVED = "alert.resolved"
      ALERT_AUTO_CLEARED = "alert.auto_cleared"
      CASE_CREATED = "case.created"
      CASE_ASSIGNED = "case.assigned"
      CASE_CLOSED = "case.closed"
      INVESTIGATION_STARTED = "investigation.started"
      INVESTIGATION_COMPLETED = "investigation.completed"
      REPORT_DRAFTED = "report.drafted"
      REPORT_APPROVED = "report.approved"
      REPORT_SUBMITTED = "report.submitted"
      KYC_ONBOARDING_COMPLETE = "kyc.onboarding_complete"
      KYC_RISK_CHANGED = "kyc.risk_changed"
      RULE_CREATED = "rule.created"
      RULE_UPDATED = "rule.updated"
  ```
- Define `PlatformEvent` model:
  - `event_id: str` (UUID)
  - `event_type: EventType`
  - `tenant_id: str`
  - `timestamp: datetime`
  - `payload: dict` — event-specific data (alert details, case summary, etc.)
  - `metadata: dict` — additional context (user_id, source)
- Implement `EventBus` (in-process, async):
  - `async emit(event: PlatformEvent)`:
    - Persists the event to the event log (DB).
    - Dispatches to all registered handlers (webhook dispatcher, governance logger, etc.).
  - `subscribe(event_type: EventType, handler: Callable)` — registers an in-process handler.
  - `unsubscribe(event_type: EventType, handler: Callable)`.

**Why:** An in-process event bus decouples event producers (API handlers, agent nodes) from consumers (webhook dispatcher, audit logger). This is lighter than a full message broker (Kafka) for the current scale while remaining extensible.

### Step 2: Define Webhook Subscription Models

**Files:**
- `src/aml/db/models/webhook.py`

**Implementation Details:**
- `WebhookSubscription` ORM model:
  - `tenant_id: str` (FK)
  - `url: str` — HTTPS endpoint to POST events to
  - `secret: str` — HMAC signing secret for signature verification
  - `event_types: list[str]` — which event types to receive (empty = all)
  - `is_active: bool = True`
  - `description: str | None`
  - `created_by: str`
  - `failure_count: int = 0` — consecutive delivery failures
  - `disabled_at: datetime | None` — auto-disabled after too many failures
- `WebhookDelivery` ORM model (delivery log):
  - `subscription_id: UUID` (FK)
  - `event_id: str`
  - `event_type: str`
  - `attempt_number: int`
  - `status: str` — `SUCCESS`, `FAILED`, `PENDING`
  - `http_status_code: int | None`
  - `response_body: str | None` (truncated)
  - `error_message: str | None`
  - `delivered_at: datetime`
  - `latency_ms: int`

**Why:** The subscription model supports per-tenant, filtered webhook registration. The delivery log provides transparency into delivery success/failure and enables debugging.

### Step 3: Implement Webhook Dispatcher

**Files:**
- `src/aml/services/events/webhook_dispatcher.py`

**Implementation Details:**
- Implement `WebhookDispatcher`:
  - Registers as a handler on the `EventBus`.
  - On event received:
    1. Loads active subscriptions for the event's tenant_id and event_type.
    2. For each subscription:
       - Constructs the webhook payload:
         ```json
         {
           "event_id": "...",
           "event_type": "alert.created",
           "timestamp": "2026-06-28T10:00:00Z",
           "tenant_id": "...",
           "data": { ... }
         }
         ```
       - Computes HMAC-SHA256 signature using the subscription's secret.
       - Sets headers: `X-Webhook-ID`, `X-Webhook-Signature`, `X-Webhook-Timestamp`.
       - POSTs to the subscription URL with a 10-second timeout.
       - Records the `WebhookDelivery`.
  - **Retry logic** (on failure):
    - Retries 5 times with exponential backoff: 30s, 2m, 10m, 1h, 6h.
    - Uses Redis-backed delayed queue for retry scheduling.
    - After 5 failures, marks delivery as `FAILED`.
  - **Auto-disable**: if a subscription has 50 consecutive failures, it is auto-disabled with a notification to the tenant admin.
  - All dispatching is async (fire-and-forget from the event bus perspective).

**Why:** Webhook delivery must be reliable but non-blocking. Retry with exponential backoff handles transient failures. Auto-disable prevents wasting resources on permanently broken endpoints. HMAC signature verification allows subscribers to authenticate that webhooks are genuine.

### Step 4: Emit Events from Existing Code

**Files:**
- `src/aml/api/routers/agents.py` (update)
- `src/aml/api/routers/alerts.py` (update)
- `src/aml/services/monitoring/evaluator.py` (update from BE-206)
- `src/aml/services/reporting/submission/service.py` (update from BE-303)
- `src/aml/services/kyc/pipeline.py` (update from BE-302)

**Implementation Details:**
- After each state change, emit the corresponding event:
  - Alert created by monitoring engine → `ALERT_CREATED`.
  - Alert auto-cleared by triage → `ALERT_AUTO_CLEARED`.
  - Investigation started → `INVESTIGATION_STARTED`.
  - Investigation completed → `INVESTIGATION_COMPLETED`.
  - Report submitted → `REPORT_SUBMITTED`.
  - KYC onboarding complete → `KYC_ONBOARDING_COMPLETE`.
- Event payloads include the relevant entity data (alert details, case summary, report metadata).

**Why:** Minimal integration: one line per state change point. The event bus handles all downstream routing.

### Step 5: Implement Event Replay

**Files:**
- `src/aml/services/events/replay.py`

**Implementation Details:**
- `EventReplayService`:
  - `async replay(subscription_id: UUID, start: datetime, end: datetime) -> int`:
    - Loads events from the event log within the time range.
    - Filters to events matching the subscription's event types.
    - Re-dispatches each event to the subscription URL.
    - Returns count of replayed events.
  - Rate-limited: max 100 events per second during replay to avoid overwhelming the subscriber.

**Why:** When a subscriber's endpoint was down during an outage, they need to catch up on missed events. Replay provides this without requiring them to poll the API.

### Step 6: Create Webhook Management API

**Files:**
- `src/aml/api/routers/webhooks.py`

**Implementation Details:**
- `POST /api/v1/webhooks` — Register a new webhook subscription. Body: `{ "url": "...", "event_types": [...], "secret": "..." }`.
- `GET /api/v1/webhooks` — List webhook subscriptions for the tenant.
- `GET /api/v1/webhooks/{id}` — Subscription details including delivery stats.
- `PUT /api/v1/webhooks/{id}` — Update subscription (URL, event types, active status).
- `DELETE /api/v1/webhooks/{id}` — Remove subscription.
- `GET /api/v1/webhooks/{id}/deliveries` — Delivery log with status and latency.
- `POST /api/v1/webhooks/{id}/test` — Send a test event to verify the endpoint.
- `POST /api/v1/webhooks/{id}/replay` — Replay events for a time range.
- `GET /api/v1/events` — List available event types.
- Register in `app.py`.

**Why:** Self-service webhook management is essential for enterprise integrations. The test endpoint allows subscribers to verify their setup before enabling the subscription.

### Step 7: Implement Tests

**Files:**
- `tests/test_webhook_platform.py`

**Implementation Details:**
- Test event emission: trigger an alert creation, verify the event is emitted.
- Test webhook delivery: register a mock endpoint, emit an event, verify POST received with correct signature.
- Test retry logic: mock a failing endpoint, verify 5 retry attempts with correct backoff.
- Test auto-disable: simulate 50 failures, verify subscription is disabled.
- Test event replay: emit 10 events, replay for a time range, verify all are re-delivered.
- Test signature verification: verify HMAC-SHA256 signature matches expected value.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Webhook floods** overwhelming subscriber | Medium | Rate limiting. Configurable batch window. |
| **Secret leakage** in logs | Critical | Secrets never logged. Masked in API responses. |
| **Event log growth** | Medium | TTL-based cleanup (30-day retention). Archival to cold storage. |
| **Replay causing duplicate processing** at subscriber | Medium | Idempotent event IDs. Subscribers should deduplicate on `event_id`. |
