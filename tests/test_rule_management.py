"""Tests for RuleManagementService (BE-305 Step 2)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.alert import AlertSeverity
from aml.db.models.rule import TenantRule
from aml.db.models.tenant import Tenant
from aml.services.monitoring.rule_management import RuleManagementService
from aml.services.monitoring.rule_schemas import CreateRuleRequest, UpdateRuleRequest


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


async def _make_tenant(db_session, slug="test-tenant") -> str:
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug=slug)
    db_session.add(tenant)
    await db_session.flush()
    return tenant_id


def _create_request(**overrides) -> CreateRuleRequest:
    defaults = {
        "rule_id": "CUST-001",
        "name": "Custom Rule",
        "description": "A test rule",
        "conditions": [{"field": "amount", "operator": "gte", "value": 10000}],
        "alert_type": "custom_alert",
        "severity": AlertSeverity.HIGH,
    }
    defaults.update(overrides)
    return CreateRuleRequest(**defaults)


class TestCreateRule:
    async def test_create_returns_tenant_rule(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        rule = await svc.create_rule(tenant_id=tenant_id, rule=_create_request())

        assert rule.id is not None
        assert rule.rule_id == "CUST-001"
        assert rule.version == 1
        assert rule.tenant_id == tenant_id

    async def test_create_validates_operator(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        with pytest.raises(ValueError, match="Invalid operator"):
            await svc.create_rule(
                tenant_id=tenant_id,
                rule=_create_request(conditions=[{"field": "x", "operator": "BADOP", "value": 1}]),
            )


class TestUpdateRule:
    async def test_update_increments_version(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request())

        updated = await svc.update_rule(
            tenant_id=tenant_id,
            rule_id="CUST-001",
            update=UpdateRuleRequest(name="Updated Name"),
            changed_by="admin",
        )

        assert updated.version == 2
        assert updated.name == "Updated Name"

    async def test_update_creates_version_record(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request())

        await svc.update_rule(
            tenant_id=tenant_id,
            rule_id="CUST-001",
            update=UpdateRuleRequest(name="V2", change_reason="Testing"),
            changed_by="admin",
        )

        versions = await svc.get_rule_versions(tenant_id=tenant_id, rule_id="CUST-001")
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].changed_by == "admin"


class TestDeleteRule:
    async def test_soft_deletes(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request())

        await svc.delete_rule(tenant_id=tenant_id, rule_id="CUST-001")

        rule = await svc.get_rule(tenant_id=tenant_id, rule_id="CUST-001")
        assert rule is None

    async def test_list_excludes_deleted(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request())
        await svc.delete_rule(tenant_id=tenant_id, rule_id="CUST-001")

        rules = await svc.list_rules(tenant_id=tenant_id)
        assert len(rules) == 0

    async def test_list_includes_deleted_when_requested(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request())
        await svc.delete_rule(tenant_id=tenant_id, rule_id="CUST-001")

        rules = await svc.list_rules(tenant_id=tenant_id, include_deleted=True)
        assert len(rules) == 1


class TestGetAndList:
    async def test_get_respects_tenant(self, db_session: AsyncSession):
        tid_a = await _make_tenant(db_session, slug="a")
        tid_b = await _make_tenant(db_session, slug="b")
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tid_a, rule=_create_request())

        assert await svc.get_rule(tenant_id=tid_b, rule_id="CUST-001") is None

    async def test_list_rules(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request(rule_id="R1"))
        await svc.create_rule(tenant_id=tenant_id, rule=_create_request(rule_id="R2"))

        rules = await svc.list_rules(tenant_id=tenant_id)
        assert len(rules) == 2


class TestTemplateAdoption:
    async def _seed_template(self, db_session):
        template = TenantRule(
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
        db_session.add(template)
        await db_session.commit()
        return template

    async def test_adopt_template(self, db_session: AsyncSession):
        template = await self._seed_template(db_session)
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        adopted = await svc.adopt_template(tenant_id=tenant_id, template_rule_id=str(template.id))

        assert adopted.tenant_id == tenant_id
        assert adopted.rule_id == "TPL-001"
        assert adopted.is_template is False
        assert adopted.conditions == template.conditions

    async def test_adopt_template_not_found(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        with pytest.raises(ValueError, match="not found"):
            await svc.adopt_template(tenant_id=tenant_id, template_rule_id=str(uuid.uuid4()))

    async def test_list_templates(self, db_session: AsyncSession):
        await self._seed_template(db_session)
        svc = RuleManagementService(session=db_session)

        templates = await svc.list_templates()
        assert len(templates) >= 1
        assert all(t.is_template for t in templates)


class TestPackAdoption:
    async def _seed_pack(self, db_session):
        for i, rid in enumerate(["P1", "P2", "P3"]):
            t = TenantRule(
                tenant_id=None,
                rule_id=rid,
                name=f"Pack Rule {i}",
                description="",
                conditions=[],
                alert_type="test",
                severity=AlertSeverity.LOW,
                is_template=True,
                pack_id="TEST-PACK",
            )
            db_session.add(t)
        await db_session.commit()

    async def test_adopt_pack(self, db_session: AsyncSession):
        await self._seed_pack(db_session)
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        adopted = await svc.adopt_pack(tenant_id=tenant_id, pack_id="TEST-PACK")

        assert len(adopted) == 3
        assert all(r.tenant_id == tenant_id for r in adopted)
        assert all(r.is_template is False for r in adopted)

    async def test_adopt_pack_empty(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        svc = RuleManagementService(session=db_session)

        adopted = await svc.adopt_pack(tenant_id=tenant_id, pack_id="NONEXISTENT")
        assert len(adopted) == 0
