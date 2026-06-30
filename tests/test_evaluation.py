"""Tests for LLM-as-Judge, golden dataset, observability, and A/B testing (Phase 5)."""

from aml.observability.spans import MetricsCollector, SpanRecord
from aml.services.evaluation.dataset import build_seed_dataset
from aml.services.evaluation.experiment import Experiment, ExperimentManager, ExperimentStatus
from aml.services.evaluation.judge import (
    AccuracyRubric,
    CompletenessRubric,
    JudgeEngine,
)


class TestGoldenDataset:
    def test_seed_dataset_non_empty(self):
        ds = build_seed_dataset()
        assert len(ds.cases) >= 5
        assert ds.version == "1.0"

    def test_coverage_by_category(self):
        ds = build_seed_dataset()
        coverage = ds.coverage
        assert "sanctions" in coverage
        assert "structuring" in coverage

    def test_filter_by_category(self):
        ds = build_seed_dataset()
        sanctions = ds.filter_by_category("sanctions")
        assert len(sanctions) >= 1
        assert all(c.category == "sanctions" for c in sanctions)

    def test_filter_by_difficulty(self):
        ds = build_seed_dataset()
        easy = ds.filter_by_difficulty("easy")
        assert len(easy) >= 1
        assert all(c.difficulty == "easy" for c in easy)


class TestAccuracyRubric:
    def test_correct_decision_scores_1(self):
        rubric = AccuracyRubric()
        score = rubric.score({"decision": "INVESTIGATE"}, {"decision": "INVESTIGATE"})
        assert score.score == 1.0

    def test_wrong_decision_scores_0(self):
        rubric = AccuracyRubric()
        score = rubric.score({"decision": "AUTO_CLEAR"}, {"decision": "INVESTIGATE"})
        assert score.score == 0.0


class TestCompletenessRubric:
    def test_all_fields_covered(self):
        rubric = CompletenessRubric()
        score = rubric.score({"decision": "X", "reason": "Y"}, {"decision": "X", "reason": "Y"})
        assert score.score == 1.0

    def test_partial_coverage(self):
        rubric = CompletenessRubric()
        score = rubric.score({"decision": "X"}, {"decision": "X", "reason": "Y"})
        assert 0 < score.score < 1.0


class TestJudgeEngine:
    def test_evaluate_case_passing(self):
        engine = JudgeEngine()
        ds = build_seed_dataset()
        case = ds.cases[0]
        output = dict(case.expected_outcome)
        evaluation = engine.evaluate_case(output, case, threshold=0.5)
        assert evaluation.passed is True
        assert evaluation.overall_score >= 0.5

    def test_evaluate_case_failing(self):
        engine = JudgeEngine()
        ds = build_seed_dataset()
        case = ds.cases[0]
        evaluation = engine.evaluate_case({"decision": "WRONG"}, case, threshold=0.85)
        assert evaluation.passed is False

    def test_evaluate_dataset(self):
        engine = JudgeEngine()
        ds = build_seed_dataset()
        results = [(dict(c.expected_outcome), c) for c in ds.cases]
        report = engine.evaluate_dataset(results, threshold=0.5)
        assert report.total_cases == len(ds.cases)
        assert report.overall_score > 0

    def test_evaluate_empty_dataset(self):
        engine = JudgeEngine()
        report = engine.evaluate_dataset([], threshold=0.85)
        assert report.total_cases == 0
        assert report.passed is False

    def test_injectable_rubrics(self):
        engine = JudgeEngine(rubrics=[AccuracyRubric()])
        ds = build_seed_dataset()
        case = ds.cases[0]
        evaluation = engine.evaluate_case(dict(case.expected_outcome), case)
        assert len(evaluation.dimension_scores) == 1


class TestMetricsCollector:
    def test_record_and_summarize(self):
        MetricsCollector.reset()
        mc = MetricsCollector.get_instance()
        mc.record_span(SpanRecord(name="test", start_time=0.0, end_time=0.1))
        mc.record_span(SpanRecord(name="test", start_time=0.0, end_time=0.5))
        summary = mc.get_summary()
        assert summary["total_spans"] == 2
        assert summary["p50_ms"] > 0

    def test_counters(self):
        MetricsCollector.reset()
        mc = MetricsCollector.get_instance()
        mc.increment("llm_calls")
        mc.increment("llm_calls")
        mc.increment("tokens", 150)
        assert mc.get_counter("llm_calls") == 2
        assert mc.get_counter("tokens") == 150

    def test_singleton(self):
        MetricsCollector.reset()
        a = MetricsCollector.get_instance()
        b = MetricsCollector.get_instance()
        assert a is b

    def test_empty_summary(self):
        MetricsCollector.reset()
        mc = MetricsCollector.get_instance()
        summary = mc.get_summary()
        assert summary["total_spans"] == 0


class TestExperimentManager:
    def test_create_and_get(self):
        mgr = ExperimentManager()
        exp = mgr.create(Experiment(name="test-exp", tenant_id="t1", variant_config={"model": "new"}))
        assert mgr.get("test-exp") is not None
        assert exp.status == ExperimentStatus.DRAFT

    def test_start_experiment(self):
        mgr = ExperimentManager()
        mgr.create(Experiment(name="exp", tenant_id="t1", variant_config={}))
        mgr.start("exp")
        assert mgr.get("exp").status == ExperimentStatus.RUNNING

    def test_pause_experiment(self):
        mgr = ExperimentManager()
        mgr.create(Experiment(name="exp", tenant_id="t1", variant_config={}))
        mgr.start("exp")
        mgr.pause("exp")
        assert mgr.get("exp").status == ExperimentStatus.PAUSED

    def test_should_shadow_run_only_when_running(self):
        exp = Experiment(name="exp", tenant_id="t1", variant_config={}, sample_rate=1.0)
        assert exp.should_shadow_run() is False
        exp.status = ExperimentStatus.RUNNING
        assert exp.should_shadow_run() is True

    def test_auto_complete_at_max_samples(self):
        exp = Experiment(name="exp", tenant_id="t1", variant_config={}, max_samples=2, status=ExperimentStatus.RUNNING)
        exp.record_sample()
        exp.record_sample()
        assert exp.status == ExperimentStatus.COMPLETED
        assert exp.should_shadow_run() is False

    def test_get_active_for_tenant(self):
        mgr = ExperimentManager()
        mgr.create(Experiment(name="e1", tenant_id="t1", variant_config={}))
        mgr.start("e1")
        assert mgr.get_active_for_tenant("t1") is not None
        assert mgr.get_active_for_tenant("t2") is None

    def test_list_by_tenant(self):
        mgr = ExperimentManager()
        mgr.create(Experiment(name="e1", tenant_id="t1", variant_config={}))
        mgr.create(Experiment(name="e2", tenant_id="t2", variant_config={}))
        assert len(mgr.list_experiments("t1")) == 1
        assert len(mgr.list_experiments()) == 2
