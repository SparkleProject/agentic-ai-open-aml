# BE-503: A/B Testing Framework — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

When upgrading models, modifying prompts, or adjusting agent configurations, we need a safe way to compare the new approach against the current production baseline. BE-503 implements an **A/B testing framework** that allows shadow-running experimental agent configurations alongside production, collecting comparison metrics, and making data-driven rollout decisions.

The framework must:
1. Allow tenants to configure experiments (different prompts, models, temperatures).
2. Shadow-run the experimental configuration on the same alerts as production (without affecting the production outcome).
3. Compare results: accuracy, latency, cost, hallucination rate.
4. Provide statistical significance testing before recommending rollout.
5. Support feature flagging per tenant.

### Dependencies on Existing Code
- `src/aml/agents/orchestrator.py` — the orchestrator that runs experiments.
- `src/aml/services/evaluation/judge.py` (from BE-501) — judge engine for comparing quality.
- `src/aml/db/models/model_registry.py` (from BE-405) — model inventory.
- `src/aml/services/governance/logger.py` (from BE-402) — logging experimental runs.

---

## 2. Architecture Approach: Shadow Execution with Statistical Comparison

```
  Alert Arrives ──> Production Agent ──> Production Result (returned to user)
       │
       └──(shadow)──> Experiment Agent ──> Experiment Result (logged, not returned)
                                                    │
                                              Judge Comparison ──> Experiment Report
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Experiment Configuration Models

**Files:**
- `src/aml/db/models/experiment.py`
- `src/aml/services/experiment/config.py`

**Implementation Details:**
- `Experiment` ORM model:
  - `name: str` — human-readable experiment name
  - `description: str`
  - `status: ExperimentStatus` — `DRAFT`, `RUNNING`, `PAUSED`, `COMPLETED`, `CANCELLED`
  - `tenant_id: str` — which tenant this experiment runs for
  - `variant_config: dict` (JSONB):
    - `model_key: str` — alternative model from registry
    - `temperature: float | None`
    - `system_prompt_override: str | None`
    - `agent_config: dict | None` — alternative agent definitions/whitelists
  - `sample_rate: float` — what percentage of alerts get shadow-run (0.0-1.0)
  - `max_samples: int` — stop after this many shadow runs
  - `started_at: datetime | None`
  - `completed_at: datetime | None`
  - `created_by: str`
- `ExperimentResult` ORM model:
  - `experiment_id: UUID` (FK)
  - `alert_id: UUID`
  - `production_output: dict` (JSONB) — the real agent's result
  - `experiment_output: dict` (JSONB) — the variant's result
  - `judge_comparison: dict | None` (JSONB) — judge engine evaluation of both
  - `production_latency_ms: int`
  - `experiment_latency_ms: int`
  - `production_tokens: int`
  - `experiment_tokens: int`

**Why:** Experiments are fully configurable and scoped to tenants. The sample rate controls cost — not every alert needs to be shadow-run. Max samples provides a natural stopping point for statistical analysis.

### Step 2: Build the Shadow Execution Engine

**Files:**
- `src/aml/services/experiment/shadow_runner.py`

**Implementation Details:**
- Implement `ShadowRunner`:
  - `async should_shadow_run(alert_id: str, tenant_id: str) -> Experiment | None`:
    - Checks for active experiments for the tenant.
    - Applies the sample rate (random selection).
    - Returns the experiment config if this alert should be shadow-run, else `None`.
  - `async run_shadow(experiment: Experiment, alert: Alert, production_result: dict) -> ExperimentResult`:
    - Builds an alternative orchestrator using the experiment's variant config:
      - Swaps the model via the model registry.
      - Applies prompt overrides.
      - Applies agent config overrides.
    - Runs the alternative orchestrator on the same alert data.
    - Records both outputs in `ExperimentResult`.
    - Optionally runs the judge engine to compare quality.
    - **Ensures the experiment result does NOT modify any database state** (read-only execution).
  - Called as a fire-and-forget background task after the production agent completes — never blocks the response.

**Why:** Shadow execution provides real-world comparison data without any risk to production. Running as a background task ensures zero latency impact on the actual investigation response.

### Step 3: Implement Statistical Analysis

**Files:**
- `src/aml/services/experiment/analysis.py`

**Implementation Details:**
- Implement `ExperimentAnalyzer`:
  - `async analyze(experiment_id: UUID) -> ExperimentReport`:
    - Loads all `ExperimentResult` records for the experiment.
    - Computes comparison metrics:
      - **Quality**: average judge score difference (experiment - production).
      - **Latency**: mean and P95 latency for both variants.
      - **Cost**: total token usage and estimated cost for both variants.
      - **Agreement rate**: how often both variants reach the same conclusion.
      - **Error rate**: failure rate for both variants.
    - **Statistical significance**: two-sample t-test on quality scores.
      - Reports p-value and confidence interval.
      - Marks the result as `SIGNIFICANT` if p < 0.05 with ≥30 samples.
    - `ExperimentReport`:
      - `experiment_id`, `total_samples`, `quality_delta`, `latency_delta_ms`, `cost_delta_usd`, `agreement_rate`, `p_value`, `is_significant`, `recommendation` (`ADOPT`, `REJECT`, `INCONCLUSIVE`).

**Why:** Statistical significance testing prevents acting on noise. Without it, natural LLM variance could make a worse model appear better in a small sample. The 30-sample minimum and p-value threshold provide rigorous decision support.

### Step 4: Integrate with Investigation Flow

**Files:**
- `src/aml/api/routers/agents.py` (update)

**Implementation Details:**
- After the production agent investigation completes, check for active experiments:
  ```python
  shadow_runner = ShadowRunner()
  experiment = await shadow_runner.should_shadow_run(alert_id, tenant_id)
  if experiment:
      # Fire-and-forget background task
      asyncio.create_task(shadow_runner.run_shadow(experiment, alert, production_result))
  ```
- The shadow run is completely invisible to the API consumer.

**Why:** Minimal integration point — a single check after the production result is ready. No changes to the investigation flow or response format.

### Step 5: Create Experiment Management API

**Files:**
- `src/aml/api/routers/experiments.py`

**Implementation Details:**
- `POST /api/v1/experiments` — Create a new experiment. Body: experiment config.
- `GET /api/v1/experiments` — List experiments for the tenant.
- `GET /api/v1/experiments/{id}` — Experiment details with current sample count.
- `POST /api/v1/experiments/{id}/start` — Start the experiment.
- `POST /api/v1/experiments/{id}/pause` — Pause shadow execution.
- `POST /api/v1/experiments/{id}/complete` — Complete and trigger analysis.
- `GET /api/v1/experiments/{id}/report` — Get the statistical analysis report.
- `GET /api/v1/experiments/{id}/results` — Paginated list of individual shadow run results.
- Register in `app.py`.

**Why:** Experiment management needs to be self-service for compliance teams evaluating new model configurations.

### Step 6: Implement Tests

**Files:**
- `tests/test_ab_testing.py`

**Implementation Details:**
- Test sample rate: with rate 0.5, verify approximately half of alerts are shadow-run.
- Test shadow execution: verify the experiment agent runs but does NOT modify database state.
- Test statistical analysis: mock 50 results with known score distributions, verify t-test calculation.
- Test recommendation logic: significant improvement → ADOPT, significant degradation → REJECT, insignificant → INCONCLUSIVE.
- Test experiment lifecycle: DRAFT → RUNNING → COMPLETED.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Shadow run modifies production data** | Critical | Experiment runs in read-only mode (no DB writes). Separate DB session. |
| **Shadow run cost** (double the LLM calls) | Medium | Sample rate control. Max sample cap. Use cheaper model for initial screening. |
| **Statistical significance never reached** | Low | Alert the experiment creator if samples are accumulating too slowly. Suggest increasing sample rate. |
| **Experiment variant crashes** | Low | Errors are caught and logged as experiment failures, not propagated to production. |
