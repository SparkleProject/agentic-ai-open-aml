"""Tests for ISO 42001 governance logging (BE-402)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.services.governance.logger import GovernanceEvent, GovernanceLogger
from aml.services.governance.verifier import ChainVerifier


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


class TestGovernanceLogger:
    async def test_log_event_creates_entry(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        event = GovernanceEvent(
            tenant_id="tenant-001",
            event_type="LLM_INVOCATION",
            agent_id="SanctionsAgent",
            input_summary="Check entity X",
            output_summary="No match found",
        )
        log = await logger.log_event(event)

        assert log.id is not None
        assert log.content_hash is not None
        assert log.prev_hash is None

    async def test_hash_chaining(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)

        log1 = await logger.log_event(
            GovernanceEvent(tenant_id="t1", event_type="E1", agent_id="A1", input_summary="first")
        )
        log2 = await logger.log_event(
            GovernanceEvent(tenant_id="t1", event_type="E2", agent_id="A1", input_summary="second")
        )

        assert log2.prev_hash == log1.content_hash
        assert log1.prev_hash is None

    async def test_tenant_isolation_in_chains(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)

        await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E1", agent_id="A1"))
        log_t2 = await logger.log_event(GovernanceEvent(tenant_id="t2", event_type="E1", agent_id="A1"))

        assert log_t2.prev_hash is None

    async def test_log_llm_invocation(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        log = await logger.log_llm_invocation(
            tenant_id="t1",
            agent_id="SanctionsAgent",
            model_id="claude-3-5-sonnet",
            prompt_summary="Screen entity",
            response_summary="No match",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1200,
        )

        assert log.event_type == "LLM_INVOCATION"
        assert log.model_id == "claude-3-5-sonnet"
        assert log.input_tokens == 100

    async def test_log_agent_decision(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        log = await logger.log_agent_decision(
            tenant_id="t1",
            agent_id="CDDAgent",
            case_id=str(uuid.uuid4()),
            decision="INVESTIGATE",
            reasoning="Multiple risk factors",
        )

        assert log.event_type == "AGENT_DECISION"
        assert log.reasoning_chain == "Multiple risk factors"

    async def test_log_human_override(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        log = await logger.log_human_override(
            tenant_id="t1",
            user_id="analyst@company.com",
            case_id=str(uuid.uuid4()),
            original_decision="AUTO_CLEAR",
            override_decision="INVESTIGATE",
            reason="Analyst disagrees with triage",
        )

        assert log.event_type == "HUMAN_OVERRIDE"
        assert log.agent_id == "analyst@company.com"


class TestChainVerifier:
    async def test_empty_chain_is_valid(self, db_session: AsyncSession):
        verifier = ChainVerifier(session=db_session)
        result = await verifier.verify_chain("empty-tenant")

        assert result.is_valid is True
        assert result.total_entries == 0

    async def test_valid_chain(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E1", agent_id="A1"))
        await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E2", agent_id="A1"))
        await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E3", agent_id="A1"))

        verifier = ChainVerifier(session=db_session)
        result = await verifier.verify_chain("t1")

        assert result.is_valid is True
        assert result.total_entries == 3

    async def test_tampered_chain_detected(self, db_session: AsyncSession):
        logger = GovernanceLogger(session=db_session)
        log1 = await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E1", agent_id="A1"))
        await logger.log_event(GovernanceEvent(tenant_id="t1", event_type="E2", agent_id="A1"))

        log1.content_hash = "tampered_hash"
        await db_session.commit()

        verifier = ChainVerifier(session=db_session)
        result = await verifier.verify_chain("t1")

        assert result.is_valid is False
        assert result.first_break_at is not None


class TestGovernanceAPI:
    async def test_list_logs(self, db_session, client: TestClient):
        tenant_id = "api-tenant-1"
        logger = GovernanceLogger(session=db_session)
        await logger.log_event(GovernanceEvent(tenant_id=tenant_id, event_type="E1", agent_id="A1"))
        await logger.log_event(GovernanceEvent(tenant_id=tenant_id, event_type="E2", agent_id="A2"))

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.get("/api/v1/governance/logs", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        client.app.dependency_overrides.clear()

    async def test_verify_endpoint(self, db_session, client: TestClient):
        tenant_id = "api-tenant-2"
        logger = GovernanceLogger(session=db_session)
        await logger.log_event(GovernanceEvent(tenant_id=tenant_id, event_type="E1", agent_id="A1"))

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.post("/api/v1/governance/verify", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is True

        client.app.dependency_overrides.clear()
