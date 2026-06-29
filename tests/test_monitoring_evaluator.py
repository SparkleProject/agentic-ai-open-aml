"""Tests for the real-time transaction evaluator (BE-206 Step 3)."""

from decimal import Decimal

import pytest

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.anomaly import AnomalyResult, AnomalyScorer, CustomerProfile
from aml.services.monitoring.evaluator import TransactionEvaluator
from aml.services.monitoring.rules import RuleEngine
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition, RuleMatch


@pytest.fixture
def sample_rule():
    return MonitoringRule(
        id="STD-001",
        name="Threshold Reporting",
        description="Inbound >= $10,000",
        conditions=[
            RuleCondition(field="amount", operator="gte", value=10000),
            RuleCondition(field="direction", operator="eq", value="inbound"),
        ],
        alert_type="threshold_reporting",
        severity=AlertSeverity.MEDIUM,
    )


@pytest.fixture
def sample_profile():
    return CustomerProfile(
        mean_amount=Decimal("5000"),
        std_amount=Decimal("1000"),
        transaction_count_90d=90,
        avg_daily_frequency=1.0,
        known_counterparties={"Acme Corp"},
        known_currencies={"AUD"},
    )


class TestTransactionEvaluator:
    def test_evaluate_returns_alerts_for_rule_match(self, sample_rule, sample_profile):
        evaluator = TransactionEvaluator()
        tx_data = {
            "amount": Decimal("15000"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[sample_rule],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        assert len(alerts) >= 1
        rule_alert = next(a for a in alerts if a.alert_type == "threshold_reporting")
        assert rule_alert.severity == AlertSeverity.MEDIUM
        assert rule_alert.tenant_id == "tenant-001"
        assert rule_alert.customer_id == "cust-001"

    def test_evaluate_returns_empty_when_no_match(self, sample_profile):
        evaluator = TransactionEvaluator()
        rule = MonitoringRule(
            id="R1",
            name="High threshold",
            description="Amount >= 1000000",
            conditions=[RuleCondition(field="amount", operator="gte", value=1000000)],
            alert_type="million_dollar",
            severity=AlertSeverity.CRITICAL,
        )
        tx_data = {
            "amount": Decimal("500"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[rule],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        assert len(alerts) == 0

    def test_evaluate_generates_anomaly_alert_for_extreme_transaction(self, sample_profile):
        evaluator = TransactionEvaluator()
        tx_data = {
            "amount": Decimal("99999"),
            "currency": "KPW",
            "direction": "inbound",
            "counterparty": "Unknown Shell Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        anomaly_alerts = [a for a in alerts if a.alert_type == "anomaly_detection"]
        assert len(anomaly_alerts) == 1
        assert anomaly_alerts[0].severity in AlertSeverity

    def test_evaluate_no_anomaly_alert_for_normal_transaction(self, sample_profile):
        evaluator = TransactionEvaluator()
        tx_data = {
            "amount": Decimal("5000"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        anomaly_alerts = [a for a in alerts if a.alert_type == "anomaly_detection"]
        assert len(anomaly_alerts) == 0

    def test_evaluate_combines_rule_and_anomaly_alerts(self, sample_rule, sample_profile):
        evaluator = TransactionEvaluator()
        tx_data = {
            "amount": Decimal("99999"),
            "currency": "KPW",
            "direction": "inbound",
            "counterparty": "Unknown Shell Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[sample_rule],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        alert_types = {a.alert_type for a in alerts}
        assert "threshold_reporting" in alert_types
        assert "anomaly_detection" in alert_types

    def test_alert_data_contains_details(self, sample_rule, sample_profile):
        evaluator = TransactionEvaluator()
        tx_data = {
            "amount": Decimal("15000"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[sample_rule],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        alert = alerts[0]
        assert alert.details is not None
        assert "rule_id" in alert.details or "anomaly_score" in alert.details

    def test_anomaly_threshold_is_configurable(self, sample_profile):
        evaluator = TransactionEvaluator(anomaly_threshold=90.0)
        tx_data = {
            "amount": Decimal("15000"),
            "currency": "IRR",
            "direction": "inbound",
            "counterparty": "New Entity",
        }
        alerts = evaluator.evaluate(
            transaction=tx_data,
            rules=[],
            profile=sample_profile,
            customer_id="cust-001",
            tenant_id="tenant-001",
        )
        anomaly_alerts = [a for a in alerts if a.alert_type == "anomaly_detection"]
        assert len(anomaly_alerts) == 0


# ---------------------------------------------------------------------------
# DIP — Dependency injection tests
# ---------------------------------------------------------------------------


class TestEvaluatorDependencyInjection:
    def test_inject_custom_rule_engine(self, sample_profile):
        class StubRuleEngine(RuleEngine):
            def evaluate(self, transaction, rules):
                return [
                    RuleMatch(
                        rule_id="STUB-001",
                        rule_name="Stub Rule",
                        alert_type="stub_alert",
                        severity=AlertSeverity.LOW,
                        matched_conditions=["always matches"],
                    )
                ]

        evaluator = TransactionEvaluator(rule_engine=StubRuleEngine())
        tx = {"amount": Decimal("1"), "currency": "AUD", "direction": "inbound"}
        alerts = evaluator.evaluate(
            transaction=tx,
            rules=[],
            profile=sample_profile,
            customer_id="c1",
            tenant_id="t1",
        )
        assert any(a.alert_type == "stub_alert" for a in alerts)

    def test_inject_custom_anomaly_scorer(self, sample_profile):
        class StubScorer(AnomalyScorer):
            def score_transaction(self, *, amount, currency, counterparty, profile):
                return AnomalyResult(score=99.0, factors=["injected scorer fired"])

        evaluator = TransactionEvaluator(anomaly_scorer=StubScorer())
        tx = {"amount": Decimal("1"), "currency": "AUD", "direction": "inbound"}
        alerts = evaluator.evaluate(
            transaction=tx,
            rules=[],
            profile=sample_profile,
            customer_id="c1",
            tenant_id="t1",
        )
        anomaly_alerts = [a for a in alerts if a.alert_type == "anomaly_detection"]
        assert len(anomaly_alerts) == 1
        assert "injected scorer fired" in anomaly_alerts[0].description
