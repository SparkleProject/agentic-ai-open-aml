"""Tests for transaction ingestion API and monitoring queue (BE-206 Step 5)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.tenant import Tenant
from aml.services.monitoring.queue import MonitoringQueue


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


class TestTransactionAPI:
    async def test_ingest_single_transaction(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test Tenant", slug="test-tenant-tx-1")
        db_session.add(tenant)
        await db_session.flush()

        customer_id = str(uuid.uuid4())

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        response = client.post(
            "/api/v1/transactions",
            json={
                "customer_id": customer_id,
                "amount": "15000.00",
                "currency": "AUD",
                "direction": "inbound",
                "counterparty": "Acme Corp",
                "description": "Invoice payment",
                "transaction_date": "2026-06-28T10:00:00Z",
            },
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 201
        data = response.json()
        assert "transaction_id" in data
        assert data["tenant_id"] == tenant_id

        client.app.dependency_overrides.clear()

    async def test_ingest_rejects_missing_tenant(self, db_session, client: TestClient):
        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        response = client.post(
            "/api/v1/transactions",
            json={
                "customer_id": str(uuid.uuid4()),
                "amount": "1000.00",
                "currency": "AUD",
                "direction": "inbound",
                "transaction_date": "2026-06-28T10:00:00Z",
            },
        )
        assert response.status_code == 400

        client.app.dependency_overrides.clear()

    async def test_ingest_batch_transactions(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Batch Tenant", slug="test-tenant-tx-batch")
        db_session.add(tenant)
        await db_session.flush()

        customer_id = str(uuid.uuid4())

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        response = client.post(
            "/api/v1/transactions/batch",
            json={
                "transactions": [
                    {
                        "customer_id": customer_id,
                        "amount": "5000.00",
                        "currency": "AUD",
                        "direction": "inbound",
                        "transaction_date": "2026-06-28T10:00:00Z",
                    },
                    {
                        "customer_id": customer_id,
                        "amount": "3000.00",
                        "currency": "AUD",
                        "direction": "outbound",
                        "counterparty": "Vendor",
                        "transaction_date": "2026-06-28T11:00:00Z",
                    },
                ]
            },
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["count"] == 2
        assert len(data["transaction_ids"]) == 2

        client.app.dependency_overrides.clear()


class TestMonitoringQueue:
    async def test_sync_fallback_publishes_and_consumes(self):
        queue = MonitoringQueue(redis_url=None)
        received: list[dict] = []

        async def handler(msg: dict):
            received.append(msg)

        await queue.publish(transaction_id="tx-001", tenant_id="tenant-001")
        await queue.consume_once(handler)

        assert len(received) == 1
        assert received[0]["transaction_id"] == "tx-001"
        assert received[0]["tenant_id"] == "tenant-001"

    async def test_sync_fallback_empty_queue(self):
        queue = MonitoringQueue(redis_url=None)
        received: list[dict] = []

        async def handler(msg: dict):
            received.append(msg)

        await queue.consume_once(handler)
        assert len(received) == 0

    async def test_multiple_messages(self):
        queue = MonitoringQueue(redis_url=None)
        received: list[dict] = []

        async def handler(msg: dict):
            received.append(msg)

        await queue.publish(transaction_id="tx-001", tenant_id="t1")
        await queue.publish(transaction_id="tx-002", tenant_id="t1")
        await queue.publish(transaction_id="tx-003", tenant_id="t2")

        await queue.consume_once(handler)
        await queue.consume_once(handler)
        await queue.consume_once(handler)

        assert len(received) == 3

    async def test_pending_count(self):
        queue = MonitoringQueue(redis_url=None)
        assert queue.pending_count == 0

        await queue.publish(transaction_id="tx-001", tenant_id="t1")
        await queue.publish(transaction_id="tx-002", tenant_id="t1")
        assert queue.pending_count == 2

        async def noop(msg: dict):
            pass

        await queue.consume_once(noop)
        assert queue.pending_count == 1
