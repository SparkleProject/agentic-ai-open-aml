"""Unit tests for database models, CRUD helpers, and tenant isolation.

Uses SQLite in-memory via aiosqlite for fast, dependency-free testing.
No real Postgres needed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.crud.base import create, delete, get_by_id, list_by_tenant, update
from aml.db.models.alert import Alert, AlertSeverity, AlertStatus
from aml.db.models.customer import Customer, CustomerType, RiskRating
from aml.db.models.tenant import Tenant

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database for each test."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def tenant_a_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def tenant_b_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    async def test_create_tenant(self, db_session: AsyncSession):
        tenant = Tenant(name="Acme Corp", slug="acme", is_active=True)
        db_session.add(tenant)
        await db_session.flush()
        assert tenant.id is not None
        assert tenant.created_at is not None

    async def test_create_customer(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t")
        db_session.add(tenant)
        await db_session.flush()

        customer = Customer(
            tenant_id=tenant_a_id,
            external_id="EXT-001",
            name="John Doe",
            customer_type=CustomerType.INDIVIDUAL,
            risk_rating=RiskRating.LOW,
        )
        db_session.add(customer)
        await db_session.flush()
        assert customer.id is not None
        assert customer.tenant_id == tenant_a_id

    async def test_alert_enums(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t-alert")
        db_session.add(tenant)
        await db_session.flush()

        alert = Alert(
            tenant_id=tenant_a_id,
            alert_type="high_value_transfer",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.NEW,
            title="Large transfer detected",
        )
        db_session.add(alert)
        await db_session.flush()
        assert alert.severity == AlertSeverity.HIGH
        assert alert.status == AlertStatus.NEW


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestCRUD:
    async def test_create_and_get(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t-crud")
        db_session.add(tenant)
        await db_session.flush()

        alert = await create(
            db_session,
            Alert,
            tenant_id=tenant_a_id,
            alert_type="sanctions_match",
            severity=AlertSeverity.CRITICAL,
            title="Sanctions hit: OFAC list",
        )
        assert alert.id is not None

        fetched = await get_by_id(db_session, Alert, record_id=alert.id, tenant_id=tenant_a_id)
        assert fetched is not None
        assert fetched.title == "Sanctions hit: OFAC list"

    async def test_list_by_tenant(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t-list")
        db_session.add(tenant)
        await db_session.flush()

        for i in range(3):
            await create(
                db_session,
                Alert,
                tenant_id=tenant_a_id,
                alert_type=f"type_{i}",
                severity=AlertSeverity.LOW,
                title=f"Alert {i}",
            )

        results = await list_by_tenant(db_session, Alert, tenant_id=tenant_a_id)
        assert len(results) == 3

    async def test_update(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t-upd")
        db_session.add(tenant)
        await db_session.flush()

        alert = await create(
            db_session,
            Alert,
            tenant_id=tenant_a_id,
            alert_type="test",
            severity=AlertSeverity.LOW,
            title="Original",
        )

        updated = await update(db_session, alert, status=AlertStatus.INVESTIGATING, title="Updated")
        assert updated.status == AlertStatus.INVESTIGATING
        assert updated.title == "Updated"

    async def test_delete(self, db_session: AsyncSession, tenant_a_id: str):
        tenant = Tenant(id=uuid.UUID(tenant_a_id), name="T", slug="t-del")
        db_session.add(tenant)
        await db_session.flush()

        alert = await create(
            db_session,
            Alert,
            tenant_id=tenant_a_id,
            alert_type="to_delete",
            severity=AlertSeverity.LOW,
            title="Bye",
        )
        await delete(db_session, alert)

        fetched = await get_by_id(db_session, Alert, record_id=alert.id, tenant_id=tenant_a_id)
        assert fetched is None


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    async def test_tenant_b_cannot_see_tenant_a_alerts(
        self, db_session: AsyncSession, tenant_a_id: str, tenant_b_id: str
    ):
        """Critical test: data belonging to Tenant A must NEVER appear in Tenant B queries."""
        # Create both tenants
        for tid, slug in [(tenant_a_id, "iso-a"), (tenant_b_id, "iso-b")]:
            db_session.add(Tenant(id=uuid.UUID(tid), name=f"T-{slug}", slug=slug))
        await db_session.flush()

        # Tenant A creates an alert
        secret_alert = await create(
            db_session,
            Alert,
            tenant_id=tenant_a_id,
            alert_type="secret",
            severity=AlertSeverity.CRITICAL,
            title="Tenant A confidential alert",
        )

        # Tenant B should NOT see it
        fetched = await get_by_id(db_session, Alert, record_id=secret_alert.id, tenant_id=tenant_b_id)
        assert fetched is None, "Tenant B must NOT see Tenant A's alert!"

        # Tenant B's list should be empty
        b_alerts = await list_by_tenant(db_session, Alert, tenant_id=tenant_b_id)
        assert len(b_alerts) == 0, "Tenant B must have zero alerts"

        # Tenant A CAN see it
        a_alerts = await list_by_tenant(db_session, Alert, tenant_id=tenant_a_id)
        assert len(a_alerts) == 1
