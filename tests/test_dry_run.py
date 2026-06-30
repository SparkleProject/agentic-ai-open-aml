"""Tests for RuleDryRunService (BE-305 Step 5)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.alert import Alert, AlertSeverity
from aml.db.models.tenant import Tenant
from aml.db.models.transaction import Transaction, TransactionDirection
from aml.services.monitoring.dry_run import DryRunResult, RuleDryRunService
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition


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


async def _seed_transactions(db_session, tenant_id, customer_id, amounts):
    for i, amount in enumerate(amounts):
        tx = Transaction(
            tenant_id=tenant_id,
            customer_id=uuid.UUID(customer_id),
            amount=Decimal(str(amount)),
            currency="AUD",
            direction=TransactionDirection.INBOUND,
            transaction_date=datetime.now(tz=UTC) - timedelta(days=i),
        )
        db_session.add(tx)
    await db_session.commit()


def _threshold_rule():
    return MonitoringRule(
        id="R1",
        name="Threshold",
        description="Amount >= 10000",
        conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
        alert_type="threshold_reporting",
        severity=AlertSeverity.MEDIUM,
    )


class TestDryRun:
    async def test_scans_transactions_and_returns_matches(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="dry-run-1")
        db_session.add(tenant)
        await db_session.flush()

        await _seed_transactions(db_session, tenant_id, customer_id, [15000, 5000, 12000, 3000])

        svc = RuleDryRunService(session=db_session)
        result = await svc.dry_run(tenant_id=tenant_id, rule=_threshold_rule())

        assert isinstance(result, DryRunResult)
        assert result.transactions_scanned == 4
        assert result.match_count == 2

    async def test_respects_days_back(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="dry-run-2")
        db_session.add(tenant)
        await db_session.flush()

        for i, amount in enumerate([15000, 5000]):
            tx = Transaction(
                tenant_id=tenant_id,
                customer_id=uuid.UUID(customer_id),
                amount=Decimal(str(amount)),
                currency="AUD",
                direction=TransactionDirection.INBOUND,
                transaction_date=datetime.now(tz=UTC) - timedelta(days=i * 60),
            )
            db_session.add(tx)
        await db_session.commit()

        svc = RuleDryRunService(session=db_session)
        result = await svc.dry_run(tenant_id=tenant_id, rule=_threshold_rule(), days_back=30)

        assert result.transactions_scanned == 1

    async def test_does_not_create_alerts(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="dry-run-3")
        db_session.add(tenant)
        await db_session.flush()

        await _seed_transactions(db_session, tenant_id, customer_id, [15000])

        svc = RuleDryRunService(session=db_session)
        await svc.dry_run(tenant_id=tenant_id, rule=_threshold_rule())

        stmt = select(Alert).where(Alert.tenant_id == tenant_id)
        result = await db_session.execute(stmt)
        assert len(result.scalars().all()) == 0

    async def test_reports_execution_time(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="dry-run-4")
        db_session.add(tenant)
        await db_session.flush()

        svc = RuleDryRunService(session=db_session)
        result = await svc.dry_run(tenant_id=tenant_id, rule=_threshold_rule())

        assert result.execution_time_ms >= 0

    async def test_empty_transactions(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="dry-run-5")
        db_session.add(tenant)
        await db_session.flush()

        svc = RuleDryRunService(session=db_session)
        result = await svc.dry_run(tenant_id=tenant_id, rule=_threshold_rule())

        assert result.transactions_scanned == 0
        assert result.match_count == 0
