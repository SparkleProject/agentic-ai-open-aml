from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from aml.services.evaluation.dataset import GoldenCase


@dataclass
class DimensionScore:
    dimension: str
    score: float
    feedback: str = ""


@dataclass
class CaseEvaluation:
    case_id: str
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = False

    def compute_overall(self, threshold: float = 0.85) -> None:
        if not self.dimension_scores:
            self.overall_score = 0.0
            self.passed = False
            return
        self.overall_score = sum(d.score for d in self.dimension_scores) / len(self.dimension_scores)
        self.passed = self.overall_score >= threshold


@dataclass
class DatasetEvaluation:
    overall_score: float
    passed: bool
    total_cases: int
    failed_cases: int
    dimension_averages: dict[str, float] = field(default_factory=dict)
    per_case_results: list[CaseEvaluation] = field(default_factory=list)


class EvaluationRubric(ABC):
    @property
    @abstractmethod
    def dimension(self) -> str: ...

    @abstractmethod
    def score(
        self,
        agent_output: dict[str, Any],
        expected: dict[str, Any],
    ) -> DimensionScore: ...


class AccuracyRubric(EvaluationRubric):
    @property
    def dimension(self) -> str:
        return "accuracy"

    def score(self, agent_output: dict[str, Any], expected: dict[str, Any]) -> DimensionScore:
        output_decision = agent_output.get("decision", "").upper()
        expected_decision = expected.get("decision", "").upper()
        matched = output_decision == expected_decision
        return DimensionScore(
            dimension="accuracy",
            score=1.0 if matched else 0.0,
            feedback=f"Expected {expected_decision}, got {output_decision}",
        )


class CompletenessRubric(EvaluationRubric):
    @property
    def dimension(self) -> str:
        return "completeness"

    def score(self, agent_output: dict[str, Any], expected: dict[str, Any]) -> DimensionScore:
        expected_keys = set(expected.keys())
        output_keys = set(agent_output.keys())
        coverage = len(expected_keys & output_keys) / max(len(expected_keys), 1)
        return DimensionScore(
            dimension="completeness",
            score=coverage,
            feedback=f"Covered {len(expected_keys & output_keys)}/{len(expected_keys)} expected fields",
        )


class JudgeEngine:
    def __init__(self, *, rubrics: list[EvaluationRubric] | None = None) -> None:
        self._rubrics = rubrics or [AccuracyRubric(), CompletenessRubric()]

    def evaluate_case(
        self,
        agent_output: dict[str, Any],
        golden_case: GoldenCase,
        *,
        threshold: float = 0.85,
    ) -> CaseEvaluation:
        scores = [rubric.score(agent_output, golden_case.expected_outcome) for rubric in self._rubrics]
        evaluation = CaseEvaluation(case_id=golden_case.case_id, dimension_scores=scores)
        evaluation.compute_overall(threshold)
        return evaluation

    def evaluate_dataset(
        self,
        results: list[tuple[dict[str, Any], GoldenCase]],
        *,
        threshold: float = 0.85,
    ) -> DatasetEvaluation:
        evaluations = [self.evaluate_case(output, case, threshold=threshold) for output, case in results]

        if not evaluations:
            return DatasetEvaluation(
                overall_score=0.0,
                passed=False,
                total_cases=0,
                failed_cases=0,
            )

        overall = sum(e.overall_score for e in evaluations) / len(evaluations)
        failed = sum(1 for e in evaluations if not e.passed)

        dim_totals: dict[str, list[float]] = {}
        for e in evaluations:
            for d in e.dimension_scores:
                dim_totals.setdefault(d.dimension, []).append(d.score)
        dim_averages = {k: sum(v) / len(v) for k, v in dim_totals.items()}

        return DatasetEvaluation(
            overall_score=overall,
            passed=overall >= threshold,
            total_cases=len(evaluations),
            failed_cases=failed,
            dimension_averages=dim_averages,
            per_case_results=evaluations,
        )
