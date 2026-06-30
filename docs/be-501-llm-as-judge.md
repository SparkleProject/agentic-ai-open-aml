# BE-501: LLM-as-a-Judge Pipeline — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Traditional unit tests cannot meaningfully evaluate the quality of LLM-generated outputs (investigation reasoning, SAR narratives, risk assessments). BE-501 implements an **LLM-as-a-Judge evaluation pipeline** where a stronger, more capable model grades the platform's agent outputs against a curated Golden Dataset.

The pipeline must:
1. Run automatically as part of CI/CD (nightly) and on-demand.
2. Evaluate multiple quality dimensions: accuracy, completeness, reasoning quality, regulatory language compliance.
3. Fail the build pipeline if quality drops below a configurable threshold (default 85%).
4. Track quality trends over time to detect gradual degradation.
5. Support comparing quality across model versions (integrates with BE-405 Model Inventory).

### Dependencies on Existing Code
- `src/aml/agents/orchestrator.py` — the agent orchestrator to evaluate.
- `src/aml/services/reporting/narrative.py` (from BE-301) — narrative generation to evaluate.
- `src/aml/services/triage/service.py` — triage decisions to evaluate.
- `src/aml/services/llm/protocol.py` — `LLMProvider` for the judge model.
- `src/aml/db/models/model_registry.py` (from BE-405) — `ModelEvaluationRecord`.

### Frontend Context
- `src/pages/ResponsibleAIDashboard.tsx` — displays accuracy trends, segment performance. Uses `mockResponsibleAIData.ts`. The API must return `AccuracyTrendPoint[]`, `BiasMetric[]`, `SegmentPerformance[]`.

---

## 2. Architecture Approach: Judge Panel with Structured Rubrics

```
  Golden Dataset ──> Agent Under Test ──> Judge Model ──> Score Aggregation ──> Report/CI Gate
  (labelled cases)    (generates output)   (grades per rubric)  (per-dimension)    (pass/fail)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Golden Dataset Format and Storage

**Files:**
- `src/aml/services/evaluation/dataset.py`
- `data/golden_dataset/` (directory)

**Implementation Details:**
- Define `GoldenCase` model:
  - `case_id: str`
  - `category: str` — typology: sanctions, structuring, pep, adverse_media, cdd, narrative
  - `input: dict` — the alert/case data to feed to the agent
  - `expected_outcome: dict`:
    - `decision: str` — expected triage decision or investigation outcome
    - `key_findings: list[str]` — facts the agent should identify
    - `tools_expected: list[str]` — tools that should be called
    - `risk_level: str` — expected risk assessment
    - `narrative_requirements: list[str]` — for SAR evaluation: required sections/facts
  - `difficulty: str` — easy, medium, hard
  - `tags: list[str]` — for filtering subsets
- `GoldenDataset` model:
  - `version: str`
  - `cases: list[GoldenCase]`
  - `metadata: dict` — creation date, contributor, total count
- Store as versioned JSON files in `data/golden_dataset/v1.json`.
- `DatasetManager`:
  - `load(version: str | None = None) -> GoldenDataset` — loads the latest or specific version.
  - `validate(dataset: GoldenDataset) -> list[str]` — validates completeness and schema.

**Why:** The golden dataset is the ground truth for evaluation. Versioning ensures reproducibility. JSON files make it easy for the team to add new test cases.

### Step 2: Implement Evaluation Rubrics

**Files:**
- `src/aml/services/evaluation/rubrics.py`

**Implementation Details:**
- Define `EvaluationRubric` protocol with dimension-specific rubric implementations:
  - **AccuracyRubric**: Did the agent reach the correct conclusion? Does the recommendation match the expected outcome?
  - **CompletenessRubric**: Did the agent identify all key findings? Were the expected tools called?
  - **ReasoningQualityRubric**: Is the reasoning chain logical? Are conclusions supported by evidence? Are there logical gaps?
  - **RegulatoryComplianceRubric**: Does the output use correct regulatory terminology? Are required report sections present?
  - **HallucinationRubric**: Does the output contain any facts not supported by the input evidence?
- Each rubric produces:
  - `score: float` (0.0 - 1.0)
  - `feedback: str` — judge's explanation of the score
  - `dimension: str` — which quality dimension this measures
- `RubricSet`: collection of rubrics with configurable weights for overall score calculation.

**Why:** Multi-dimensional evaluation prevents gaming. A model that is accurate but hallucinates details would pass an accuracy-only test but fail the hallucination rubric. Weighted scoring allows adjusting emphasis (e.g., hallucination weight higher for narrative generation).

### Step 3: Implement the Judge Engine

**Files:**
- `src/aml/services/evaluation/judge.py`

**Implementation Details:**
- Implement `JudgeEngine`:
  - `async evaluate_case(agent_output: dict, golden_case: GoldenCase, rubrics: RubricSet) -> CaseEvaluation`:
    - For each rubric, constructs a judge prompt:
      - System: "You are an expert AML compliance evaluator. Grade the following agent output against the rubric."
      - Includes: the rubric criteria, the expected outcome, and the agent's actual output.
      - Instructs the judge to output JSON: `{ "score": 0.0-1.0, "feedback": "..." }`.
    - Uses a **strong judge model** (configured via model registry, purpose `EVALUATION`).
    - Low temperature (0.1) for deterministic grading.
    - Returns `CaseEvaluation`: `case_id`, `dimension_scores: dict[str, DimensionScore]`, `overall_score: float`, `pass: bool`.
  - `async evaluate_dataset(dataset: GoldenDataset, agent_runner: Callable) -> DatasetEvaluation`:
    - Runs each golden case through the agent.
    - Evaluates each agent output with the judge.
    - Aggregates scores into `DatasetEvaluation`:
      - `overall_score: float` (weighted average across all cases)
      - `dimension_averages: dict[str, float]`
      - `per_case_results: list[CaseEvaluation]`
      - `pass: bool` (overall_score >= threshold)
      - `worst_cases: list[CaseEvaluation]` — bottom 5 performers
      - `segment_scores: dict[str, float]` — score by typology category

**Why:** The judge engine automates what would otherwise be manual expert review. Using a stronger model as the judge (e.g., Claude Opus evaluating Claude Sonnet outputs) provides a reliable quality signal. Segment scores reveal if the agent is weak on specific typologies.

### Step 4: Build CI/CD Integration

**Files:**
- `src/aml/services/evaluation/ci_runner.py`
- `scripts/run_evaluation.py`

**Implementation Details:**
- `ci_runner.py`:
  - `async run_ci_evaluation(threshold: float = 0.85) -> CIResult`:
    - Loads the latest golden dataset.
    - Runs the evaluation pipeline.
    - Returns `CIResult`: `passed: bool`, `score: float`, `threshold: float`, `report_path: str`.
    - Writes a detailed report to a JSON file.
- `scripts/run_evaluation.py`:
  - CLI entry point: `python -m scripts.run_evaluation --threshold 0.85 --dataset v1`.
  - Exits with code 0 (pass) or 1 (fail) for CI integration.
  - Prints a summary table to stdout.
- GitHub Actions integration (documented, not implemented here):
  - Add a nightly workflow that runs the evaluation script.
  - Block PR merges if evaluation fails.

**Why:** Automated evaluation in CI/CD catches quality regressions before they reach production. The threshold is configurable per environment (stricter for production, lenient for development).

### Step 5: Implement Evaluation History and Trends

**Files:**
- `src/aml/db/models/evaluation_run.py`
- `src/aml/services/evaluation/history.py`

**Implementation Details:**
- `EvaluationRun` ORM model:
  - `run_id: UUID`
  - `model_key: str` (which model was evaluated)
  - `dataset_version: str`
  - `overall_score: float`
  - `dimension_scores: dict` (JSONB)
  - `segment_scores: dict` (JSONB)
  - `passed: bool`
  - `threshold: float`
  - `triggered_by: str` — `ci`, `manual`, `model_change`
  - `total_cases: int`
  - `failed_cases: int`
- `EvaluationHistoryService`:
  - `async get_trend(model_key: str, days: int = 30) -> list[EvaluationRun]`
  - `async compare_models(model_key_a: str, model_key_b: str) -> ComparisonReport`
  - `async get_segment_trends(model_key: str) -> dict[str, list[float]]` — score per typology over time
- These feed into the `ResponsibleAIDashboard` FE components:
  - `AccuracyTrendChart`: uses `get_trend()`.
  - `SegmentPerformanceChart`: uses `get_segment_trends()`.

**Why:** Trends detect gradual degradation that any single evaluation run might miss. Model comparison supports the BE-405 model lifecycle — validate a new model against the incumbent before activation.

### Step 6: Create Evaluation API

**Files:**
- `src/aml/api/routers/evaluation.py`

**Implementation Details:**
- `POST /api/v1/evaluation/run` — Trigger an evaluation run. Body: `{ "model_key": "...", "dataset_version": "..." }`.
- `GET /api/v1/evaluation/runs` — List evaluation runs with scores and pass/fail.
- `GET /api/v1/evaluation/runs/{run_id}` — Detailed results including per-case scores.
- `GET /api/v1/evaluation/trends` — Score trends over time for the active model.
- `GET /api/v1/evaluation/compare` — Compare two models' evaluation results.
- Register in `app.py`.

**Why:** These endpoints power the FE ResponsibleAIDashboard and allow compliance teams to monitor agent quality.

### Step 7: Implement Tests

**Files:**
- `tests/test_evaluation_pipeline.py`

**Implementation Details:**
- Test rubric scoring with known inputs: high-quality output → high score, poor output → low score.
- Test CI gate: score above threshold → pass, below → fail.
- Test trend tracking: create multiple evaluation runs, verify trend query returns correct order.
- Test model comparison: evaluate same dataset with two mock models, verify comparison report.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Judge model bias** (systematically over/under-scoring) | Medium | Calibrate rubrics against human expert scores. Use multiple rubric dimensions. |
| **Golden dataset too small** for reliable signal | Medium | Start with 50+ cases. Community contribution pipeline. Target 500+ cases. |
| **Evaluation cost** (running agents + judge on 500 cases) | Medium | Nightly runs only. Subset evaluation for PRs (top-20 critical cases). |
| **Non-deterministic agent outputs** cause flaky CI | Medium | Run each case 3 times, use median score. Set temperature to 0 for evaluated runs. |
