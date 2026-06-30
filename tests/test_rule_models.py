"""Tests for TenantRule and RuleVersion ORM models (BE-305 Step 1)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.alert import AlertSeverity
from aml.db.models.rule import RuleVersion, TenantRule
from aml.db.models.tenant import Tenant


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_tenant(db_session, slug="test-tenant") -> tuple[Tenant, str]:
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug=slug)
    db_session.add(tenant)
    await db_session.flush()
    return tenant, tenant_id


class TestTenantRuleModel:
    async def test_create_tenant_rule(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session)
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="CUST-001",
            name="Custom Rule",
            description="Test rule",
            conditions=[{"field": "amount", "operator": "gte", "value": 10000}],
            alert_type="custom_alert",
            severity=AlertSeverity.HIGH,
        )
        db_session.add(rule)
        await db_session.commit()

        assert rule.id is not None
        assert rule.rule_id == "CUST-001"
        assert rule.tenant_id == tenant_id

    async def test_default_values(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session)
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="R1",
            name="Test",
            description="Desc",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        db_session.add(rule)
        await db_session.commit()

        assert rule.enabled is True
        assert rule.is_template is False
        assert rule.is_deleted is False
        assert rule.version == 1
        assert rule.entity_type is None
        assert rule.pack_id is None

    async def test_template_rule_no_tenant(self, db_session: AsyncSession):
        rule = TenantRule(
            tenant_id=None,
            rule_id="TPL-001",
            name="Template Rule",
            description="A template",
            conditions=[{"field": "amount", "operator": "gte", "value": 5000}],
            alert_type="template_alert",
            severity=AlertSeverity.MEDIUM,
            is_template=True,
            pack_id="T2-GENERAL",
        )
        db_session.add(rule)
        await db_session.commit()

        assert rule.is_template is True
        assert rule.tenant_id is None
        assert rule.pack_id == "T2-GENERAL"

    async def test_soft_delete(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session)
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="DEL-001",
            name="To Delete",
            description="Will be soft deleted",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        db_session.add(rule)
        await db_session.commit()

        rule.is_deleted = True
        await db_session.commit()

        stmt = select(TenantRule).where(
            TenantRule.tenant_id == tenant_id,
            TenantRule.is_deleted == False,  # noqa: E712
        )
        result = await db_session.execute(stmt)
        active_rules = result.scalars().all()
        assert len(active_rules) == 0

    async def test_tenant_isolation(self, db_session: AsyncSession):
        _, tid_a = await _make_tenant(db_session, slug="tenant-a")
        _, tid_b = await _make_tenant(db_session, slug="tenant-b")

        rule_a = TenantRule(
            tenant_id=tid_a,
            rule_id="R1",
            name="A's Rule",
            description="",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        rule_b = TenantRule(
            tenant_id=tid_b,
            rule_id="R1",
            name="B's Rule",
            description="",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        db_session.add_all([rule_a, rule_b])
        await db_session.commit()

        stmt = select(TenantRule).where(TenantRule.tenant_id == tid_a)
        result = await db_session.execute(stmt)
        rules = result.scalars().all()
        assert len(rules) == 1
        assert rules[0].name == "A's Rule"

    async def test_conditions_stored_as_json(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session, slug="json-test")
        conditions = [
            {"field": "amount", "operator": "gte", "value": 10000},
            {"field": "direction", "operator": "eq", "value": "inbound"},
        ]
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="J1",
            name="JSON Test",
            description="",
            conditions=conditions,
            alert_type="test",
            severity=AlertSeverity.MEDIUM,
        )
        db_session.add(rule)
        await db_session.commit()
        await db_session.refresh(rule)

        assert len(rule.conditions) == 2
        assert rule.conditions[0]["field"] == "amount"


class TestRuleVersionModel:
    async def test_create_version(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session, slug="version-test")
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="V1",
            name="Versioned",
            description="",
            conditions=[{"field": "amount", "operator": "gte", "value": 100}],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        db_session.add(rule)
        await db_session.commit()

        version = RuleVersion(
            tenant_rule_id=rule.id,
            version=1,
            conditions=rule.conditions,
            alert_type=rule.alert_type,
            severity=rule.severity,
            enabled=rule.enabled,
            changed_by="admin@company.com",
            change_reason="Initial creation",
        )
        db_session.add(version)
        await db_session.commit()

        assert version.id is not None
        assert version.version == 1
        assert version.changed_by == "admin@company.com"

    async def test_multiple_versions(self, db_session: AsyncSession):
        _, tenant_id = await _make_tenant(db_session, slug="multi-version")
        rule = TenantRule(
            tenant_id=tenant_id,
            rule_id="MV1",
            name="Multi",
            description="",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        db_session.add(rule)
        await db_session.commit()

        for i in range(1, 4):
            v = RuleVersion(
                tenant_rule_id=rule.id,
                version=i,
                conditions=[{"field": "amount", "operator": "gte", "value": i * 1000}],
                alert_type="test",
                severity=AlertSeverity.LOW,
                enabled=True,
                changed_by="user",
                change_reason=f"Version {i}",
            )
            db_session.add(v)
        await db_session.commit()

        stmt = select(RuleVersion).where(RuleVersion.tenant_rule_id == rule.id)
        result = await db_session.execute(stmt)
        versions = result.scalars().all()
        assert len(versions) == 3
