"""Tests for RuleSeeder (BE-305 Step 6)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.rule import TenantRule
from aml.services.monitoring.rule_seeder import RuleSeeder


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


class TestRuleSeeder:
    async def test_seed_creates_templates(self, db_session: AsyncSession):
        seeder = RuleSeeder(session=db_session)
        count = await seeder.seed_templates()

        assert count > 0

        stmt = select(TenantRule).where(TenantRule.is_template == True)  # noqa: E712
        result = await db_session.execute(stmt)
        templates = result.scalars().all()
        assert len(templates) == count

    async def test_seed_is_idempotent(self, db_session: AsyncSession):
        seeder = RuleSeeder(session=db_session)
        count_1 = await seeder.seed_templates()
        count_2 = await seeder.seed_templates()

        assert count_1 > 0
        assert count_2 == 0

    async def test_templates_have_correct_flags(self, db_session: AsyncSession):
        seeder = RuleSeeder(session=db_session)
        await seeder.seed_templates()

        stmt = select(TenantRule).where(TenantRule.is_template == True)  # noqa: E712
        result = await db_session.execute(stmt)
        for template in result.scalars().all():
            assert template.is_template is True
            assert template.tenant_id is None
            assert template.is_deleted is False

    async def test_templates_have_pack_ids(self, db_session: AsyncSession):
        seeder = RuleSeeder(session=db_session)
        await seeder.seed_templates()

        stmt = select(TenantRule).where(TenantRule.is_template == True)  # noqa: E712
        result = await db_session.execute(stmt)
        pack_ids = {t.pack_id for t in result.scalars().all()}
        assert "T2-GENERAL" in pack_ids
        assert "T2-REAL-ESTATE" in pack_ids
        assert "T2-LEGAL" in pack_ids
        assert "T2-ACCOUNTING" in pack_ids

    async def test_list_packs(self, db_session: AsyncSession):
        seeder = RuleSeeder(session=db_session)
        packs = seeder.list_packs()
        assert len(packs) == 4
        assert "T2-GENERAL" in packs
