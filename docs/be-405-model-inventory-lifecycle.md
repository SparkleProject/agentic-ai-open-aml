# BE-405: Model Inventory & Lifecycle — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

The platform uses multiple AI models for different tasks: reasoning (Claude 3.5 Sonnet), embeddings (Titan), triage (potentially a smaller/faster model), and evaluation (a stronger judge model). ISO 42001 requires:
1. A **registry of all models in use**: version, purpose, training data lineage, performance metrics.
2. **Traceability**: "which model made this decision?" for any historical AI action.
3. **Lifecycle management**: safe deprecation, replacement, and rollback of models.
4. **Approval workflows**: new models must be validated before production use.

Currently, model selection is hardcoded in `Settings` (`bedrock_model_id`, `ollama_model`). There is no formal inventory, no approval workflow, and no way to trace which model version produced a given output.

### Dependencies on Existing Code
- `src/aml/core/config.py` — `Settings` with model IDs.
- `src/aml/services/llm/factory.py` — `get_llm_provider()` factory.
- `src/aml/services/embedding/factory.py` — `get_embedding_provider()` factory.
- `src/aml/db/models/governance_log.py` (from BE-402) — `model_id` and `model_version` fields.

---

## 2. Architecture Approach: Model Registry with Lifecycle State Machine

```
  Model Registration ──> Validation ──> Approval ──> Active ──> Deprecated ──> Retired
                              │              │           │             │
                          Eval pipeline   Human sign-off  In-use     Migration
                          (BE-501)                                   period
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Model Registry Data Models

**Files:**
- `src/aml/db/models/model_registry.py`

**Implementation Details:**
- Define `RegisteredModel` ORM model extending `Base`:
  - `model_key: str` — unique identifier (e.g., `claude-3-5-sonnet-reasoning`)
  - `provider: str` — `bedrock`, `azure`, `ollama`, `openai`
  - `model_id: str` — provider-specific model identifier
  - `model_version: str` — specific version/checkpoint
  - `purpose: ModelPurpose` — enum: `REASONING`, `EMBEDDING`, `TRIAGE`, `EVALUATION`, `NARRATIVE`, `GUARDRAIL`
  - `status: ModelStatus` — enum: `REGISTERED`, `VALIDATING`, `APPROVED`, `ACTIVE`, `DEPRECATED`, `RETIRED`
  - `performance_metrics: dict | None` (JSONB) — latest evaluation scores
  - `configuration: dict | None` (JSONB) — default params (temperature, max_tokens, system prompt template)
  - `approved_by: str | None`
  - `approved_at: datetime | None`
  - `deprecated_at: datetime | None`
  - `replacement_model_key: str | None` — points to the successor model
  - `notes: str | None` — human-readable notes about the model
- Define `ModelEvaluationRecord`:
  - `model_key: str` (FK)
  - `evaluated_at: datetime`
  - `dataset_id: str` — which golden dataset was used
  - `metrics: dict` (JSONB) — accuracy, latency, cost, quality scores
  - `passed_threshold: bool`

**Why:** A formal model registry replaces scattered config values. The lifecycle states ensure models go through validation before production use and are systematically retired rather than abandoned.

### Step 2: Implement Model Registry Service

**Files:**
- `src/aml/services/model_registry/service.py`

**Implementation Details:**
- Implement `ModelRegistryService`:
  - `async register_model(model: RegisterModelRequest) -> RegisteredModel`:
    - Creates a model entry in `REGISTERED` status.
    - Validates the provider and model_id are reachable (basic connectivity check).
  - `async get_active_model(purpose: ModelPurpose) -> RegisteredModel`:
    - Returns the current `ACTIVE` model for the given purpose.
    - Raises an error if no active model exists for the purpose.
  - `async approve_model(model_key: str, approved_by: str)`:
    - Moves from `VALIDATING` → `APPROVED`.
    - Requires passing evaluation metrics (from BE-501 integration).
  - `async activate_model(model_key: str)`:
    - Sets the model to `ACTIVE` for its purpose.
    - Deactivates any previously active model for the same purpose (moves to `DEPRECATED`).
    - Logs the switch in the governance log.
  - `async deprecate_model(model_key: str, replacement_key: str | None)`:
    - Moves to `DEPRECATED`. Sets `replacement_model_key`.
  - `async retire_model(model_key: str)`:
    - Moves to `RETIRED`. Only allowed if no governance logs reference this model in the last 30 days.
  - `async list_models(purpose: ModelPurpose | None, status: ModelStatus | None) -> list[RegisteredModel]`.

**Why:** The service enforces the lifecycle state machine. Only one model can be `ACTIVE` per purpose at any time, preventing conflicts. The retirement check ensures we don't lose audit traceability.

### Step 3: Update LLM and Embedding Factories

**Files:**
- `src/aml/services/llm/factory.py` (update)
- `src/aml/services/embedding/factory.py` (update)

**Implementation Details:**
- Update `get_llm_provider()`:
  - Instead of reading `settings.llm_provider` and `settings.bedrock_model_id` directly, query `ModelRegistryService.get_active_model(ModelPurpose.REASONING)`.
  - Use the registered model's `provider`, `model_id`, and `configuration` to construct the provider.
  - Fall back to `settings` values if the registry has no active model (backwards compatibility during migration).
- Update `get_embedding_provider()` similarly: query `ModelRegistryService.get_active_model(ModelPurpose.EMBEDDING)`.
- The model_id and version from the registry are passed through to the governance logger (BE-402) for every invocation.

**Why:** This closes the traceability loop: the registry controls which model is active → the factory uses it → the governance logger records it. Every AI decision can be traced to a specific registered, approved model version.

### Step 4: Create Model Management API

**Files:**
- `src/aml/api/routers/models.py`

**Implementation Details:**
- `GET /api/v1/models` — List all registered models with their status and metrics.
- `POST /api/v1/models` — Register a new model. Requires `TENANT_CONFIGURE` permission.
- `GET /api/v1/models/{model_key}` — Model details including evaluation history.
- `POST /api/v1/models/{model_key}/approve` — Approve a validated model.
- `POST /api/v1/models/{model_key}/activate` — Activate a model for its purpose.
- `POST /api/v1/models/{model_key}/deprecate` — Deprecate with optional replacement.
- `GET /api/v1/models/active` — List currently active models by purpose.
- Register in `app.py`.

**Why:** These endpoints support the future FE model management dashboard and enable compliance officers to manage model lifecycle without code deployments.

### Step 5: Seed Default Model Registry

**Files:**
- `src/aml/services/model_registry/seed.py`

**Implementation Details:**
- `async seed_default_models(settings: Settings)`:
  - Registers models from the current `Settings` values:
    - Reasoning: `bedrock_model_id` or `ollama_model` → registered with purpose `REASONING`, status `ACTIVE`.
    - Embedding: `ollama_embedding_model` or `bedrock_embedding_model_id` → purpose `EMBEDDING`, status `ACTIVE`.
  - Only seeds if no models exist in the registry (first run).
- Called during app startup in `lifespan`.

**Why:** Ensures backwards compatibility. Existing deployments automatically populate the registry from their current settings, avoiding a breaking migration.

### Step 6: Implement Tests

**Files:**
- `tests/test_model_registry.py`

**Implementation Details:**
- Test lifecycle: REGISTERED → VALIDATING → APPROVED → ACTIVE → DEPRECATED → RETIRED.
- Test single-active constraint: activating a model deactivates the previous one.
- Test factory integration: verify `get_llm_provider()` uses the registry.
- Test retirement guard: cannot retire a model referenced in recent governance logs.
- Test seed: verify default models are created from settings on first run.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Model switch breaks agent behaviour** | High | Validation evaluation (BE-501) required before approval. Rollback by reactivating previous model. |
| **Registry downtime blocks all LLM calls** | Critical | Factory falls back to `Settings` values if registry is unavailable. In-memory cache of active models. |
| **Model version drift** between registry and actual provider | Medium | Periodic health check validates the registered model is still available from the provider. |
| **Orphaned models** never cleaned up | Low | Periodic audit report showing models in each lifecycle state. |
