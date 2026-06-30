"""Tests for rule management API (BE-305 Step 7)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.alert import AlertSeverity
from aml.db.models.rule import TenantRule
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


def _setup_db(client, db_session):
    from aml.db.session import get_db

    async def override_db():
        yield db_session

    client.app.dependency_overrides[get_db] = override_db


def _rule_payload(**overrides):
    defaults = {
        "rule_id": "CUST-001",
        "name": "Custom Rule",
        "description": "Test",
        "conditions": [{"field": "amount", "operator": "gte", "value": 10000}],
        "alert_type": "custom",
        "severity": "high",
    }
    defaults.update(overrides)
    return defaults


class TestCreateRule:
    async def test_create_success(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-1"))
        await db_session.flush()

        _setup_db(client, db_session)
        resp = client.post("/api/v1/rules", json=_rule_payload(), headers={"X-Tenant-ID": tenant_id})

        assert resp.status_code == 201
        data = resp.json()
        assert data["rule_id"] == "CUST-001"
        assert data["version"] == 1

        client.app.dependency_overrides.clear()

    async def test_create_invalid_operator(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-2"))
        await db_session.flush()

        _setup_db(client, db_session)
        resp = client.post(
            "/api/v1/rules",
            json=_rule_payload(conditions=[{"field": "x", "operator": "BADOP", "value": 1}]),
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 422

        client.app.dependency_overrides.clear()


class TestListAndGetRule:
    async def test_list_rules(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-3"))
        await db_session.flush()

        _setup_db(client, db_session)
        client.post("/api/v1/rules", json=_rule_payload(rule_id="R1"), headers={"X-Tenant-ID": tenant_id})
        client.post("/api/v1/rules", json=_rule_payload(rule_id="R2"), headers={"X-Tenant-ID": tenant_id})

        resp = client.get("/api/v1/rules", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert len(resp.json()["rules"]) == 2

        client.app.dependency_overrides.clear()

    async def test_get_rule(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-4"))
        await db_session.flush()

        _setup_db(client, db_session)
        client.post("/api/v1/rules", json=_rule_payload(), headers={"X-Tenant-ID": tenant_id})

        resp = client.get("/api/v1/rules/CUST-001", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert resp.json()["rule_id"] == "CUST-001"

        client.app.dependency_overrides.clear()

    async def test_get_rule_not_found(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-5"))
        await db_session.flush()

        _setup_db(client, db_session)
        resp = client.get("/api/v1/rules/NONEXISTENT", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 404

        client.app.dependency_overrides.clear()


class TestUpdateRule:
    async def test_update_increments_version(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-6"))
        await db_session.flush()

        _setup_db(client, db_session)
        client.post("/api/v1/rules", json=_rule_payload(), headers={"X-Tenant-ID": tenant_id})

        resp = client.put(
            "/api/v1/rules/CUST-001",
            json={"name": "Updated", "change_reason": "Testing"},
            headers={"X-Tenant-ID": tenant_id},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2
        assert resp.json()["name"] == "Updated"

        client.app.dependency_overrides.clear()


class TestDeleteRule:
    async def test_soft_delete(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-7"))
        await db_session.flush()

        _setup_db(client, db_session)
        client.post("/api/v1/rules", json=_rule_payload(), headers={"X-Tenant-ID": tenant_id})

        resp = client.delete("/api/v1/rules/CUST-001", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 204

        resp = client.get("/api/v1/rules/CUST-001", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 404

        client.app.dependency_overrides.clear()


class TestVersions:
    async def test_get_versions(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-8"))
        await db_session.flush()

        _setup_db(client, db_session)
        client.post("/api/v1/rules", json=_rule_payload(), headers={"X-Tenant-ID": tenant_id})
        client.put("/api/v1/rules/CUST-001", json={"name": "V2"}, headers={"X-Tenant-ID": tenant_id})

        resp = client.get("/api/v1/rules/CUST-001/versions", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert len(resp.json()["versions"]) == 1

        client.app.dependency_overrides.clear()


class TestTemplatesAndPacks:
    async def _seed_template(self, db_session):
        t = TenantRule(
            tenant_id=None,
            rule_id="TPL-001",
            name="Template",
            description="",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
            is_template=True,
            pack_id="T2-GENERAL",
        )
        db_session.add(t)
        await db_session.commit()
        return t

    async def test_list_templates(self, db_session, client: TestClient):
        await self._seed_template(db_session)

        _setup_db(client, db_session)
        resp = client.get("/api/v1/rules/templates")
        assert resp.status_code == 200
        assert len(resp.json()["templates"]) >= 1

        client.app.dependency_overrides.clear()

    async def test_adopt_template(self, db_session, client: TestClient):
        template = await self._seed_template(db_session)
        tenant_id = str(uuid.uuid4())
        db_session.add(Tenant(id=uuid.UUID(tenant_id), name="T", slug="rules-9"))
        await db_session.flush()

        _setup_db(client, db_session)
        resp = client.post(
            f"/api/v1/rules/adopt-template/{template.id}",
            headers={"X-Tenant-ID": tenant_id},
        )
        assert resp.status_code == 201
        assert resp.json()["rule_id"] == "TPL-001"
        assert resp.json()["is_template"] is False

        client.app.dependency_overrides.clear()

    async def test_list_packs(self, db_session, client: TestClient):
        _setup_db(client, db_session)
        resp = client.get("/api/v1/rules/templates/packs")
        assert resp.status_code == 200
        assert "T2-GENERAL" in resp.json()["packs"]

        client.app.dependency_overrides.clear()
