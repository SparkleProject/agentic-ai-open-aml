# BE-504: Golden Dataset Curation — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

BE-501 (LLM-as-a-Judge) depends on a curated **Golden Dataset** of labelled AML cases with known-good outcomes. BE-504 provides the infrastructure for managing, versioning, and growing this dataset over time.

The system must:
1. Provide a structured format for test cases covering diverse AML typologies.
2. Support versioned dataset releases for reproducible evaluations.
3. Enable community contributions (open-source typologies) with review workflow.
4. Generate synthetic test cases from real anonymised patterns.
5. Track dataset coverage across typology categories to identify gaps.

### Dependencies on Existing Code
- `src/aml/services/evaluation/dataset.py` (from BE-501) — `GoldenCase`, `GoldenDataset` models.
- `src/aml/db/models/alert.py` — Alert model (test cases simulate alerts).
- `src/aml/db/models/transaction.py` — Transaction model (test cases contain transactions).

---

## 2. Architecture Approach: Versioned Dataset Store with Contribution Pipeline

```
  Case Contribution ──> Validation ──> Review ──> Merge into Dataset ──> Version Release
  (manual/synthetic)    (schema check)  (human)   (append + metadata)    (immutable snapshot)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Extended Golden Case Schema

**Files:**
- `src/aml/services/evaluation/dataset.py` (update from BE-501)

**Implementation Details:**
- Extend `GoldenCase` with additional fields for comprehensive coverage:
  - `jurisdiction: str` — AU, NZ, US, UK (tests regulatory formatting)
  - `customer_profile: dict` — mock customer data (type, risk, jurisdiction)
  - `transactions: list[dict]` — mock transaction set
  - `expected_tools_called: list[str]` — which tools the agent should invoke
  - `expected_delegation: list[str] | None` — expected delegation chain
  - `expected_triage_decision: str` — AUTO_CLEAR or INVESTIGATE
  - `expected_narrative_sections: dict[str, str] | None` — for SAR evaluation
  - `contributor: str` — who created this case
  - `review_status: str` — PENDING, APPROVED, REJECTED
  - `quality_score: float | None` — how useful this case is for evaluation (meta-metric)
- Define `DatasetRelease` model:
  - `version: str` (semver)
  - `release_date: str`
  - `total_cases: int`
  - `coverage: dict[str, int]` — count per typology category
  - `changelog: str`
  - `checksum: str` — SHA-256 of the dataset file for integrity

**Why:** Extended schemas ensure each test case is self-contained and can exercise the full pipeline (triage → investigation → narrative). Coverage tracking identifies blind spots.

### Step 2: Build Dataset Management Service

**Files:**
- `src/aml/services/evaluation/dataset_manager.py`

**Implementation Details:**
- Implement `DatasetManager`:
  - `load(version: str | None = None) -> GoldenDataset`:
    - Loads from `data/golden_dataset/vN.json`.
    - If no version specified, loads the latest.
    - Validates checksums.
  - `add_case(case: GoldenCase) -> None`:
    - Validates the case schema.
    - Checks for duplicates (similar input + expected_outcome).
    - Appends to the working dataset.
  - `release(version: str, changelog: str) -> DatasetRelease`:
    - Freezes the current working dataset into an immutable release.
    - Computes coverage statistics and checksum.
    - Writes to `data/golden_dataset/v{version}.json`.
  - `get_coverage() -> dict[str, int]`:
    - Returns case count by typology: sanctions, structuring, pep, adverse_media, cdd, narrative, velocity, jurisdiction_risk.
  - `get_gaps(min_cases_per_category: int = 10) -> list[str]`:
    - Returns typology categories below the minimum threshold.

**Why:** The dataset manager provides a controlled workflow for dataset evolution. Checksums prevent accidental corruption. Coverage analysis guides where new cases are most needed.

### Step 3: Implement Synthetic Case Generator

**Files:**
- `src/aml/services/evaluation/synthetic.py`

**Implementation Details:**
- Implement `SyntheticCaseGenerator`:
  - `async generate(typology: str, count: int, difficulty: str = "medium") -> list[GoldenCase]`:
    - Uses an LLM to generate realistic but synthetic AML test cases.
    - Prompt: "Generate a realistic AML investigation scenario for the [typology] category. Include: customer profile, transaction history, expected investigation outcome, and key findings."
    - **Diversity controls**:
      - Varies customer types (individual, entity, trust).
      - Varies jurisdictions (AU, NZ).
      - Varies difficulty (obvious → subtle patterns).
      - Varies amount ranges and currencies.
    - Post-generation validation: ensures each case has all required fields and the expected outcome is internally consistent.
  - `async fill_gaps(dataset: GoldenDataset, target_per_category: int = 20) -> list[GoldenCase]`:
    - Identifies under-represented categories.
    - Generates synthetic cases to fill gaps.
    - Returns generated cases for human review before merging.

**Why:** Building 500+ hand-crafted test cases is impractical. Synthetic generation bootstraps the dataset quickly. Human review (Step 4) ensures quality. The diversity controls prevent the dataset from being biased toward a single pattern.

### Step 4: Create Dataset Contribution API

**Files:**
- `src/aml/api/routers/dataset.py`

**Implementation Details:**
- `POST /api/v1/dataset/cases` — Submit a new golden case for review.
  - Body: `GoldenCase` JSON.
  - Returns: case with `review_status: PENDING`.
- `GET /api/v1/dataset/cases` — List cases with filtering by category, status, difficulty.
- `POST /api/v1/dataset/cases/{case_id}/approve` — Approve a contributed case.
- `POST /api/v1/dataset/cases/{case_id}/reject` — Reject with reason.
- `POST /api/v1/dataset/generate` — Trigger synthetic generation for a typology.
  - Body: `{ "typology": "structuring", "count": 10, "difficulty": "hard" }`.
- `GET /api/v1/dataset/coverage` — Dataset coverage statistics.
- `GET /api/v1/dataset/releases` — List all dataset versions.
- `POST /api/v1/dataset/releases` — Create a new dataset release.
- Register in `app.py`.

**Why:** API-driven contribution enables both the platform team and the open-source community to add test cases. The review workflow (approve/reject) maintains quality control.

### Step 5: Seed Initial Golden Dataset

**Files:**
- `data/golden_dataset/v1.json`
- `src/aml/services/evaluation/seed.py`

**Implementation Details:**
- Create an initial dataset of **50 hand-crafted cases** covering:
  - 10 sanctions-related cases (clear matches, fuzzy matches, false positives).
  - 10 structuring cases (obvious, subtle, legitimate high-volume).
  - 8 PEP cases (direct PEP, associate, false positive).
  - 7 adverse media cases (relevant, irrelevant, outdated).
  - 5 CDD/entity unwrapping cases (simple chain, complex trust, circular ownership).
  - 5 narrative generation cases (SMR quality evaluation).
  - 5 triage cases (clear false positives, borderline, critical).
- Each case includes full input data, expected outcomes, and key findings.
- Implement `seed_golden_dataset()` to copy the initial dataset into the data directory on first run.

**Why:** 50 cases provides a meaningful starting point for evaluation while being feasible to hand-craft with domain expertise. The distribution targets the most common AML typologies.

### Step 6: Implement Tests

**Files:**
- `tests/test_dataset_management.py`

**Implementation Details:**
- Test dataset loading: verify the initial v1 dataset loads correctly.
- Test case addition: add a case, verify it appears in the working set.
- Test release: create a release, verify immutability (cannot modify after release).
- Test coverage: verify coverage stats match actual case counts.
- Test gap detection: remove cases from a category, verify the gap is detected.
- Test synthetic generation: verify generated cases have all required fields.
- Test duplicate detection: submit a near-duplicate case, verify it's flagged.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Synthetic cases not realistic enough** | Medium | Human review required before merging. Quality score tracking. Community feedback loop. |
| **Dataset drift** from evolving platform capabilities | Medium | Versioned releases tied to platform versions. Deprecation of cases testing removed features. |
| **Community contributions with poor quality** | Medium | Review workflow with approval gates. Auto-validation of schema completeness. |
| **Dataset too small for statistical significance** | Medium | Target 500+ cases. Synthetic generation fills gaps. Coverage monitoring alerts on thin areas. |
