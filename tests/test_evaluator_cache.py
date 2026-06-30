"""Tests for evaluator cache integration (BE-305 Step 4)."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.anomaly import CustomerProfile
from aml.services.monitoring.evaluator import TransactionEvaluator
from aml.services.monitoring.rule_cache import RuleCache
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition


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


def _matching_rule():
    return MonitoringRule(
        id="R1",
        name="Threshold",
        description="Amount >= 10000",
        conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
        alert_type="threshold_reporting",
        severity=AlertSeverity.MEDIUM,
    )


class TestEvaluateWithCache:
    async def test_loads_rules_from_cache(self, sample_profile):
        cache = RuleCache(ttl_seconds=60.0, loader=AsyncMock(return_value=[]))
        cache.get_rules = AsyncMock(return_value=[_matching_rule()])

        evaluator = TransactionEvaluator(rule_cache=cache)
        tx = {"amount": Decimal("15000"), "currency": "AUD", "direction": "inbound", "counterparty": "Acme Corp"}

        alerts = await evaluator.evaluate_with_cache(
            transaction=tx,
            tenant_id="t1",
            customer_id="c1",
            profile=sample_profile,
        )

        cache.get_rules.assert_awaited_once()
        assert len(alerts) >= 1
        assert any(a.alert_type == "threshold_reporting" for a in alerts)

    async def test_passes_entity_type_to_cache(self, sample_profile):
        cache = RuleCache(ttl_seconds=60.0, loader=AsyncMock(return_value=[]))
        cache.get_rules = AsyncMock(return_value=[])

        evaluator = TransactionEvaluator(rule_cache=cache)
        tx = {"amount": Decimal("100"), "currency": "AUD", "direction": "inbound"}

        await evaluator.evaluate_with_cache(
            transaction=tx,
            tenant_id="t1",
            customer_id="c1",
            entity_type="real_estate",
            profile=sample_profile,
        )

        cache.get_rules.assert_awaited_once_with(tenant_id="t1", entity_type="real_estate")

    async def test_raises_without_cache(self, sample_profile):
        evaluator = TransactionEvaluator()
        tx = {"amount": Decimal("100"), "currency": "AUD", "direction": "inbound"}

        with pytest.raises(RuntimeError, match="rule_cache not configured"):
            await evaluator.evaluate_with_cache(
                transaction=tx,
                tenant_id="t1",
                customer_id="c1",
                profile=sample_profile,
            )

    async def test_existing_evaluate_still_works(self, sample_profile):
        evaluator = TransactionEvaluator()
        rule = _matching_rule()
        tx = {"amount": Decimal("15000"), "currency": "AUD", "direction": "inbound", "counterparty": "Acme Corp"}

        alerts = evaluator.evaluate(
            transaction=tx,
            rules=[rule],
            profile=sample_profile,
            customer_id="c1",
            tenant_id="t1",
        )

        assert len(alerts) >= 1
