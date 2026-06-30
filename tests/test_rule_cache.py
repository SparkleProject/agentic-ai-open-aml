"""Tests for RuleCache with TTL (BE-305 Step 3)."""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.rule_cache import RuleCache
from aml.services.monitoring.schemas import MonitoringRule


@dataclass
class FakeTenantRule:
    rule_id: str = "R1"
    name: str = "Test Rule"
    description: str = "Desc"
    conditions: list[dict[str, Any]] = field(
        default_factory=lambda: [{"field": "amount", "operator": "gte", "value": 10000}],
    )
    alert_type: str = "test"
    severity: AlertSeverity = AlertSeverity.MEDIUM
    enabled: bool = True
    is_deleted: bool = False
    entity_type: str | None = None


def _make_tenant_rule(**overrides) -> FakeTenantRule:
    return FakeTenantRule(**overrides)


class TestRuleCacheGetRules:
    async def test_loads_from_loader_on_miss(self):
        rules = [_make_tenant_rule()]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        result = await cache.get_rules(tenant_id="tenant-001")

        assert len(result) == 1
        assert isinstance(result[0], MonitoringRule)
        loader.assert_awaited_once()

    async def test_returns_cached_on_hit(self):
        rules = [_make_tenant_rule()]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        await cache.get_rules(tenant_id="tenant-001")
        await cache.get_rules(tenant_id="tenant-001")

        assert loader.await_count == 1

    async def test_reloads_after_ttl(self):
        rules = [_make_tenant_rule()]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=0.0, loader=loader)

        await cache.get_rules(tenant_id="tenant-001")
        await cache.get_rules(tenant_id="tenant-001")

        assert loader.await_count == 2

    async def test_filters_by_entity_type(self):
        rules = [
            _make_tenant_rule(rule_id="R1", entity_type=None),
            _make_tenant_rule(rule_id="R2", entity_type="real_estate"),
            _make_tenant_rule(rule_id="R3", entity_type="legal"),
        ]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        result = await cache.get_rules(tenant_id="tenant-001", entity_type="real_estate")
        rule_ids = {r.id for r in result}
        assert "R1" in rule_ids
        assert "R2" in rule_ids
        assert "R3" not in rule_ids

    async def test_excludes_disabled_rules(self):
        rules = [
            _make_tenant_rule(rule_id="R1", enabled=True),
            _make_tenant_rule(rule_id="R2", enabled=False),
        ]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        result = await cache.get_rules(tenant_id="tenant-001")
        assert len(result) == 1
        assert result[0].id == "R1"


class TestRuleCacheInvalidation:
    async def test_invalidate_clears_tenant(self):
        loader = AsyncMock(return_value=[_make_tenant_rule()])
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        await cache.get_rules(tenant_id="tenant-001")
        cache.invalidate("tenant-001")
        await cache.get_rules(tenant_id="tenant-001")

        assert loader.await_count == 2

    async def test_invalidate_all(self):
        loader = AsyncMock(return_value=[_make_tenant_rule()])
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        await cache.get_rules(tenant_id="tenant-001")
        await cache.get_rules(tenant_id="tenant-002")
        cache.invalidate_all()
        await cache.get_rules(tenant_id="tenant-001")

        assert loader.await_count == 3


class TestRuleCacheConversion:
    async def test_converts_orm_to_monitoring_rule(self):
        rules = [
            _make_tenant_rule(
                rule_id="STD-001",
                name="Threshold",
                conditions=[{"field": "amount", "operator": "gte", "value": 10000}],
                alert_type="threshold_reporting",
                severity=AlertSeverity.HIGH,
                entity_type="real_estate",
            )
        ]
        loader = AsyncMock(return_value=rules)
        cache = RuleCache(ttl_seconds=60.0, loader=loader)

        result = await cache.get_rules(tenant_id="tenant-001")
        mr = result[0]

        assert isinstance(mr, MonitoringRule)
        assert mr.id == "STD-001"
        assert mr.name == "Threshold"
        assert mr.severity == AlertSeverity.HIGH
        assert mr.entity_type == "real_estate"
        assert len(mr.conditions) == 1
