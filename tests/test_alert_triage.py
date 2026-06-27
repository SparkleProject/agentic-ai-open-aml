import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.alert import Alert, AlertSeverity, AlertStatus
from aml.db.models.tenant import Tenant
from aml.services.llm.mock import MockLLMProvider
from aml.services.triage.service import AlertTriageService


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


@pytest.mark.asyncio
async def test_alert_triage_auto_clear(db_session: AsyncSession, client: TestClient):
    """Test that a low-risk alert is auto-cleared by triage and skips agent execution."""
    MockLLMProvider.canned_responses = [
        # Triage response
        """
        {
            "score": 10,
            "decision": "AUTO_CLEAR",
            "rationale": "Clear false positive."
        }
        """
    ]

    tenant_id_str = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id_str), name="Test Tenant", slug="test-tenant-triage-1")
    db_session.add(tenant)
    await db_session.flush()

    alert = Alert(
        tenant_id=tenant_id_str,
        alert_type="sanctions_match",
        severity=AlertSeverity.LOW,
        status=AlertStatus.NEW,
        title="False Positive Match",
        description="Low risk match.",
    )
    db_session.add(alert)
    await db_session.commit()

    from aml.db.session import get_db

    async def override_db():
        yield db_session

    client.app.dependency_overrides[get_db] = override_db

    response = client.post(
        f"/api/v1/agents/alerts/{alert.id}/investigate",
        headers={"X-Tenant-ID": tenant_id_str},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["final_alert_status"] == "false_positive"
    assert "triage" in data["conclusion"]["narrative"].lower()

    await db_session.refresh(alert)
    assert alert.status == AlertStatus.FALSE_POSITIVE
    assert alert.details is not None
    assert "triage" in alert.details

    client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_alert_triage_investigate(db_session: AsyncSession, client: TestClient):
    """Test that a high-risk alert proceeds to agent orchestration."""
    MockLLMProvider.canned_responses = [
        # Triage response
        """
        {
            "score": 85,
            "decision": "INVESTIGATE",
            "rationale": "High risk detected."
        }
        """,
        # Planner response
        "1. Do step 1",
        # Reasoner response
        """{"decision": "CONCLUDE", "conclusion": "Resolved high risk"}""",
    ]

    tenant_id_str = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id_str), name="Test Tenant 2", slug="test-tenant-triage-2")
    db_session.add(tenant)
    await db_session.flush()

    alert = Alert(
        tenant_id=tenant_id_str,
        alert_type="structuring_patterns",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        title="High Risk Structuring",
        description="Suspicious multiple deposits.",
    )
    db_session.add(alert)
    await db_session.commit()

    from aml.db.session import get_db

    async def override_db():
        yield db_session

    client.app.dependency_overrides[get_db] = override_db

    response = client.post(
        f"/api/v1/agents/alerts/{alert.id}/investigate",
        headers={"X-Tenant-ID": tenant_id_str},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["final_alert_status"] == "resolved"

    await db_session.refresh(alert)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.details is not None
    assert "triage" in alert.details
    assert alert.details["triage"]["score"] == 85

    client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Unit Tests — AlertTriageService in isolation (Step 3 edge cases)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_triage_service_auto_clear_unit():
    """Unit test: AlertTriageService returns AUTO_CLEAR for low-risk alerts without hitting API."""
    MockLLMProvider.canned_responses = [
        '{"score": 5, "decision": "AUTO_CLEAR", "rationale": "Benign threshold match."}'
    ]

    # Build a minimal Alert-like object
    alert = Alert(
        tenant_id="unit-tenant",
        alert_type="threshold_breach",
        severity=AlertSeverity.LOW,
        status=AlertStatus.NEW,
        title="Low value transfer",
        description="$50 transfer matching broad rule.",
    )

    service = AlertTriageService(rag_service=None)
    result = await service.triage_alert(alert)

    assert result.decision == "AUTO_CLEAR"
    assert result.score == 5
    assert "benign" in result.rationale.lower()


@pytest.mark.asyncio
async def test_triage_service_investigate_unit():
    """Unit test: AlertTriageService returns INVESTIGATE for high-risk alerts."""
    MockLLMProvider.canned_responses = [
        '{"score": 92, "decision": "INVESTIGATE", "rationale": "Multiple structuring indicators."}'
    ]

    alert = Alert(
        tenant_id="unit-tenant",
        alert_type="structuring_patterns",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        title="Repeated sub-threshold deposits",
        description="12 deposits of $9,900 within 48 hours.",
    )

    service = AlertTriageService(rag_service=None)
    result = await service.triage_alert(alert)

    assert result.decision == "INVESTIGATE"
    assert result.score == 92
    assert "structuring" in result.rationale.lower()


@pytest.mark.asyncio
async def test_triage_service_fallback_on_bad_json():
    """Unit test: AlertTriageService falls back to INVESTIGATE when LLM returns garbage."""
    MockLLMProvider.canned_responses = ["This is not valid JSON at all!!!"]

    alert = Alert(
        tenant_id="unit-tenant",
        alert_type="sanctions_match",
        severity=AlertSeverity.MEDIUM,
        status=AlertStatus.NEW,
        title="Partial name match",
        description="Name similarity with sanctioned entity.",
    )

    service = AlertTriageService(rag_service=None)
    result = await service.triage_alert(alert)

    # Should default to high-risk INVESTIGATE on parse failure
    assert result.decision == "INVESTIGATE"
    assert result.score == 100
    assert "failed to parse" in result.rationale.lower()


# ---------------------------------------------------------------------------
# Tenant-Policy Context Isolation (Step 3 edge case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_triage_tenant_policy_isolation():
    """Verify that triage RAG queries only retrieve the correct tenant's policies."""
    from aml.services.embedding.mock import MockEmbeddingProvider
    from aml.services.rag.service import RAGService
    from aml.services.vector_db.mock import MockVectorStore

    # Build a real RAG service with mock providers
    embedder = MockEmbeddingProvider(dims=1024)
    store = MockVectorStore()
    rag = RAGService(embedding_provider=embedder, vector_store=store)
    await rag.initialise()

    # Ingest a policy for tenant-A only
    await rag.ingest(
        text="Tenant A policy: Transfers under $500 between verified accounts are always low-risk false positives.",
        tenant_id="tenant-A",
        source="tenant-a-policy.pdf",
    )

    # Ingest a different policy for tenant-B
    await rag.ingest(
        text="Tenant B policy: All sanctions matches require full investigation regardless of amount.",
        tenant_id="tenant-B",
        source="tenant-b-policy.pdf",
    )

    # Triage an alert under tenant-A — should see tenant-A context only
    alert_a = Alert(
        tenant_id="tenant-A",
        alert_type="threshold_breach",
        severity=AlertSeverity.LOW,
        status=AlertStatus.NEW,
        title="Low value transfer",
        description="$200 transfer between verified accounts.",
    )

    service = AlertTriageService(rag_service=rag)
    result_a = await service.triage_alert(alert_a)

    # The triage should have run (regardless of mock decision). Verify RAG isolation
    # by querying directly and asserting tenant-A can't see tenant-B policies.
    results_a = await rag.query(question="sanctions investigation policy", tenant_id="tenant-A", limit=5)
    results_b = await rag.query(question="low-risk false positives", tenant_id="tenant-B", limit=5)

    # Tenant-A should NOT see tenant-B's sanctions policy
    for r in results_a:
        assert "tenant b" not in str(r.get("text", "")).lower(), "Tenant-A saw Tenant-B's policy!"

    # Tenant-B should NOT see tenant-A's false-positive policy
    for r in results_b:
        assert "tenant a" not in str(r.get("text", "")).lower(), "Tenant-B saw Tenant-A's policy!"

    # The triage result itself should be valid
    assert result_a.decision in ("AUTO_CLEAR", "INVESTIGATE")
    assert 0 <= result_a.score <= 100
    assert len(result_a.rationale) > 0
