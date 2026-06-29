# BE-402: ISO 42001 Governance Logging — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

ISO 42001 is the international standard for AI Management Systems. Regulated financial institutions adopting AI must demonstrate:
1. Every AI decision has a traceable reasoning chain.
2. The model version, configuration, and inputs/outputs are recorded immutably.
3. Human overrides are logged alongside the original AI recommendation.
4. Audit logs are exportable for regulatory review.

Currently, the platform logs via structlog (console/JSON) and stores agent reasoning in `Case.reasoning` (JSONB). This is insufficient for ISO 42001: logs are ephemeral (not immutable), there is no hash-chaining for tamper-evidence, and there is no structured query capability for auditors.

BE-402 builds an **immutable, append-only governance ledger** for every AI decision.

### Dependencies on Existing Code
- `src/aml/core/logging.py` — existing structlog configuration.
- `src/aml/db/models/case.py` — `Case.reasoning` JSONB.
- `src/aml/agents/nodes.py` — all agent nodes where AI decisions are made.
- `src/aml/services/llm/protocol.py` — LLM invocations that must be logged.

### Frontend Context
- `src/pages/AuditTrailExplorer.tsx` — FE audit trail viewer uses `mockAuditTrailData.ts`. Expects `AuditLogEntry` with `id`, `timestamp`, `tenantId`, `agentId`, `modelId`, `caseId`, `action`, `inputTokens`, `outputTokens`, `latencyMs`, `status`, `details.prompt`, `details.response`, `details.reasoningChain`.

---

## 2. Architecture Approach: Append-Only Ledger with Hash Chaining

```
  AI Decision Event ──> Governance Logger ──> Append-Only Table (DB) ──> Query API ──> FE Audit Explorer
                             │                      │                         │
                        Hash Chaining           Tamper Detection           Export (CSV/JSON)
                        (prev_hash + content)   (verification endpoint)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Governance Log Data Model

**Files:**
- `src/aml/db/models/governance_log.py`

**Implementation Details:**
- Define `GovernanceLog` ORM model extending `Base` (not TenantMixin — logs span system scope but contain tenant_id as a field):
  - `id: UUID` (primary key)
  - `tenant_id: str` (indexed, not FK — logs survive tenant deletion)
  - `timestamp: datetime` (server-generated, indexed)
  - `event_type: str` — enum: `LLM_INVOCATION`, `TOOL_EXECUTION`, `AGENT_DECISION`, `HUMAN_OVERRIDE`, `REPORT_GENERATION`, `REPORT_SUBMISSION`
  - `agent_id: str` — which agent/service produced this event
  - `case_id: UUID | None` — linked case
  - `alert_id: UUID | None` — linked alert
  - `model_id: str | None` — LLM model identifier (e.g., `claude-3-5-sonnet`)
  - `model_version: str | None` — specific model version/checkpoint
  - `system_prompt_hash: str | None` — SHA-256 of the system prompt (not the prompt itself, to save space)
  - `input_summary: str` — truncated/hashed input (full input stored separately if needed)
  - `output_summary: str` — truncated output
  - `input_tokens: int | None`
  - `output_tokens: int | None`
  - `latency_ms: int | None`
  - `temperature: float | None`
  - `status: str` — `SUCCESS`, `ERROR`, `BLOCKED_BY_GUARDRAIL`, `HUMAN_OVERRIDE`
  - `reasoning_chain: str | None` — serialised reasoning steps
  - `metadata_: dict | None` (JSONB) — additional context (tool names, parameters, guardrail results)
  - `content_hash: str` — SHA-256 of this log entry's content fields
  - `prev_hash: str | None` — hash of the previous log entry in this tenant's chain
- Table-level constraints:
  - No `UPDATE` or `DELETE` — enforce via application layer and DB triggers/policies.
  - Composite index on `(tenant_id, timestamp)` for efficient range queries.

**Why:** The hash-chaining (`content_hash` referencing `prev_hash`) creates a tamper-evident log. If any entry is modified, the chain breaks and can be detected during verification. This mirrors blockchain-like integrity guarantees without the overhead.

### Step 2: Implement Governance Logger Service

**Files:**
- `src/aml/services/governance/logger.py`

**Implementation Details:**
- Implement `GovernanceLogger` (singleton):
  - `async log_event(event: GovernanceEvent) -> GovernanceLog`:
    - Computes `content_hash` from event fields using SHA-256.
    - Retrieves the latest log entry for this tenant to get `prev_hash`.
    - Inserts the log entry with hash chaining.
    - Emits a structlog event for real-time monitoring.
  - Convenience methods for common event types:
    - `log_llm_invocation(tenant_id, agent_id, model_id, prompt, response, tokens, latency)`
    - `log_tool_execution(tenant_id, agent_id, tool_name, params, result)`
    - `log_agent_decision(tenant_id, agent_id, case_id, decision, reasoning)`
    - `log_human_override(tenant_id, user_id, case_id, original_decision, override_decision, reason)`
  - **Batching**: for high-throughput scenarios, supports batch insert with a configurable flush interval (default: every 100 events or 5 seconds).
  - **Async**: logging must never block the main request path. Uses a background queue.

**Why:** A centralised logger ensures consistent formatting and hash-chaining across all event sources. Convenience methods reduce the chance of missing required fields. Async/batched insertion prevents logging from degrading API latency.

### Step 3: Instrument Agent Nodes and LLM Provider

**Files:**
- `src/aml/agents/nodes.py` (update)
- `src/aml/services/guardrails/guarded_llm.py` (update from BE-401)
- `src/aml/services/triage/service.py` (update)
- `src/aml/services/reporting/narrative.py` (update from BE-301)

**Implementation Details:**
- **LLM Provider instrumentation** (in `GuardedLLMProvider` or a new `LoggedLLMProvider` wrapper):
  - After every `generate_response()` call, emit `log_llm_invocation()` with model ID, prompt hash, response, token counts, latency.
  - Capture the model ID and version from the provider instance.
- **Agent node instrumentation**:
  - `planner_node`: log `AGENT_DECISION` with the generated plan.
  - `reasoner_node`: log `AGENT_DECISION` with the decision (TOOL/CONCLUDE/DELEGATE).
  - `actor_node`: log `TOOL_EXECUTION` with tool name, params, and result.
  - `reflector_node`: log `AGENT_DECISION` with the final conclusion.
- **Triage service**: log each triage decision (AUTO_CLEAR or INVESTIGATE).
- **Narrative service**: log report generation events.

**Why:** Instrumentation at both the LLM layer and the agent layer captures the full decision chain. The LLM layer logs raw model interactions; the agent layer logs the higher-level decisions. Together, they provide the complete XAI trace an auditor needs.

### Step 4: Implement Chain Integrity Verification

**Files:**
- `src/aml/services/governance/verifier.py`

**Implementation Details:**
- Implement `ChainVerifier`:
  - `async verify_chain(tenant_id: str, start: datetime | None, end: datetime | None) -> VerificationResult`:
    - Loads log entries for the tenant in chronological order.
    - For each entry, recomputes the `content_hash` and verifies it matches.
    - Verifies `prev_hash` matches the prior entry's `content_hash`.
    - Returns `VerificationResult`: `is_valid: bool`, `total_entries: int`, `first_break_at: UUID | None`, `verified_range: (start, end)`.
  - Runs automatically on a schedule (daily) or on demand via API.

**Why:** Verification proves the log has not been tampered with. This is the ISO 42001 compliance guarantee — a regulator can request verification of any time range and receive cryptographic proof of integrity.

### Step 5: Create Governance API Router

**Files:**
- `src/aml/api/routers/governance.py`

**Implementation Details:**
- `GET /api/v1/governance/logs` — Paginated log listing with filters:
  - Query params: `tenant_id`, `event_type`, `agent_id`, `model_id`, `case_id`, `status`, `start_date`, `end_date`, `limit`, `offset`.
  - Response matches the `AuditLogEntry` shape expected by the FE `AuditTrailExplorer.tsx`.
- `GET /api/v1/governance/logs/{log_id}` — Full log entry detail including reasoning chain.
- `POST /api/v1/governance/verify` — Triggers chain integrity verification.
  - Request body: `{ "start_date": "...", "end_date": "..." }` (optional — defaults to last 30 days).
  - Returns the `VerificationResult`.
- `GET /api/v1/governance/export` — Exports logs as CSV or JSON for regulatory submission.
  - Query params: `format` (csv, json), `start_date`, `end_date`.
  - Streams the response for large datasets.
- Register in `app.py`.

**Why:** These endpoints replace `mockAuditTrailData.ts` in the FE. The export endpoint is specifically for regulatory audits. The verify endpoint provides on-demand tamper-evidence checking.

### Step 6: Implement Human Override Tracking

**Files:**
- `src/aml/services/governance/override.py`

**Implementation Details:**
- Implement `OverrideTracker`:
  - `async record_override(case_id: UUID, user_id: str, original_decision: dict, override_decision: dict, reason: str)`:
    - Logs a `HUMAN_OVERRIDE` governance event.
    - Links to the original `AGENT_DECISION` log entry.
    - Stores both the AI recommendation and the human's override with their stated reason.
  - Used when an analyst:
    - Changes an agent's recommended action (e.g., overrides AUTO_CLEAR to INVESTIGATE).
    - Edits an AI-drafted narrative (tracks the diff).
    - Rejects an AI-generated risk score and manually assigns a different one.
- Expose via API: `POST /api/v1/governance/override` — records an analyst override.

**Why:** Human override tracking is a core ISO 42001 requirement. Regulators need to know: when did a human disagree with the AI? What did the AI recommend? What did the human decide instead, and why? This data also feeds into the RLHF pipeline (Phase 5).

### Step 7: Implement Tests

**Files:**
- `tests/test_governance_logging.py`
- `tests/test_chain_verification.py`

**Implementation Details:**
- Test log creation: verify all required fields are populated, hash is computed correctly.
- Test hash chaining: create 10 sequential logs, verify chain integrity passes.
- Test tamper detection: manually modify a log entry's content, verify chain integrity fails.
- Test API: verify filtering, pagination, export format.
- Test human override: record an override, verify it links to the original decision.
- Test instrumented agent nodes: run the orchestrator, verify governance logs are created for every step.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **High write volume degrades DB performance** | Medium | Async batched inserts. Partitioned table by month. Archive old partitions to cold storage. |
| **Hash chain breaks during concurrent writes** | Medium | Tenant-level serialisation for hash chaining (advisory lock). |
| **Large prompt/response storage costs** | Medium | Store hashes of prompts by default. Full content only for flagged events. Configurable retention. |
| **Log export performance** for large datasets | Medium | Streaming CSV/JSON response. Background export job for very large ranges. |
