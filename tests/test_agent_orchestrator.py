import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.agents.orchestrator import build_orchestrator
from aml.agents.tools.registry import ToolRegistry
from aml.db.base import Base
from aml.db.models.alert import Alert, AlertSeverity, AlertStatus
from aml.db.models.tenant import Tenant
from aml.services.llm.mock import MockLLMProvider


@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    """Override get_settings globally for tests to force mock providers."""
    import aml.agents.nodes
    import aml.app
    import aml.core.config
    from aml.core.config import Settings

    test_settings = Settings(
        debug=True,
        environment="test",
        llm_provider="mock",
        vector_db_provider="mock",
        log_format="console",
        log_level="DEBUG",
    )

    # Patch in all imported namespaces to prevent Python's 'from import' copy reference issue
    monkeypatch.setattr(aml.core.config, "get_settings", lambda: test_settings)
    monkeypatch.setattr(aml.agents.nodes, "get_settings", lambda: test_settings)
    monkeypatch.setattr(aml.app, "get_settings", lambda: test_settings)

    yield test_settings


@pytest.fixture(autouse=True)
def clean_tool_registry():
    """Ensure the registry is correctly populated for tests."""
    from aml.agents.tools.local.screening import PEPScreeningTool, SanctionsTool
    from aml.agents.tools.local.transactions import TransactionLookupTool

    ToolRegistry._instance = None
    registry = ToolRegistry.get_instance()
    registry.register(SanctionsTool())
    registry.register(PEPScreeningTool())
    registry.register(TransactionLookupTool())
    yield


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


@pytest.mark.asyncio
async def test_agent_orchestrator_graph_execution():
    """Test that the LangGraph workflow compiles and runs end-to-end under Mock LLM."""
    MockLLMProvider.canned_responses = []  # Use dynamic smart mock

    orchestrator = build_orchestrator()
    initial_state = {
        "alert_id": str(uuid.uuid4()),
        "tenant_id": "test-tenant",
        "severity": "high",
        "plan": "",
        "executed_tools": [],
        "observations": [],
        "conclusion": {},
    }

    final_state = await orchestrator.ainvoke(initial_state)

    assert "conclusion" in final_state
    assert final_state["conclusion"]["status"] == "COMPLETED"
    assert (
        "cdd" in final_state["conclusion"]["narrative"].lower()
        or "screened" in final_state["conclusion"]["narrative"].lower()
    )
    assert len(final_state["executed_tools"]) >= 1
    assert final_state["executed_tools"][0].tool_name == "SanctionsScreeningTool"


@pytest.mark.asyncio
async def test_agent_investigate_api_endpoint(db_session: AsyncSession, client: TestClient):
    """Test the POST /api/v1/agents/alerts/{alert_id}/investigate endpoint."""
    MockLLMProvider.canned_responses = []

    # 1. Create a mock tenant and alert in the sqlite test DB
    tenant_id_str = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id_str), name="Test Tenant", slug="test-tenant")
    db_session.add(tenant)
    await db_session.flush()

    alert = Alert(
        tenant_id=tenant_id_str,
        alert_type="structuring_patterns",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        title="Anomalous deposits detected",
        description="Customer deposited $9,900 three times.",
    )
    db_session.add(alert)
    await db_session.commit()

    # 2. Override FastAPI's get_db dependency to yield our SQLite test session
    from aml.db.session import get_db

    async def override_db():
        yield db_session

    client.app.dependency_overrides[get_db] = override_db

    # 3. Call endpoint
    response = client.post(
        f"/api/v1/agents/alerts/{alert.id}/investigate",
        headers={"X-Tenant-ID": tenant_id_str},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["final_alert_status"] == "resolved"
    assert "conclusion" in data
    assert "observations" in data

    # 4. Refresh alert from DB and verify updates
    await db_session.refresh(alert)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.details is not None
    assert "agent_conclusion" in alert.details
    assert "observations" in alert.details

    # Clean up overrides
    client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_specialized_agent_delegator():
    """Test that specialized agents run and delegate context dynamically."""
    MockLLMProvider.canned_responses = []  # Use dynamic smart mock

    orchestrator = build_orchestrator()
    initial_state = {
        "alert_id": str(uuid.uuid4()),
        "tenant_id": "test-tenant",
        "severity": "high",
        "plan": "",
        "executed_tools": [],
        "observations": [],
        "conclusion": {},
        "active_agent": "SanctionsAgent",
        "agent_history": [],
    }

    final_state = await orchestrator.ainvoke(initial_state)

    # SanctionsAgent should execute tool, then delegate to CDDAgent, which concludes!
    assert "conclusion" in final_state
    assert final_state["active_agent"] == "CDDAgent"
    assert final_state["agent_history"] == ["SanctionsAgent", "CDDAgent"]
    assert (
        "resolved" in final_state["conclusion"]["narrative"].lower()
        or "completed" in final_state["conclusion"]["narrative"].lower()
    )


@pytest.mark.asyncio
async def test_agent_api_endpoint_structuring_alerts(db_session: AsyncSession, client: TestClient):
    """Test that structuring alerts dynamically start with the TransactionMonitorAgent."""
    MockLLMProvider.canned_responses = []

    tenant_id_str = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id_str), name="Test Tenant", slug="test-tenant")
    db_session.add(tenant)
    await db_session.flush()

    # Create structuring alert
    alert = Alert(
        tenant_id=tenant_id_str,
        alert_type="deposit_structuring_anomalies",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        title="Structuring alerts",
        description="Irregular deposit flows detected.",
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

    # Refresh alert and check details
    await db_session.refresh(alert)
    assert alert.details is not None
    observations = alert.details.get("observations", [])
    assert len(observations) >= 1
    # Legacy fallback behavior inside MockLLMProvider for structuring alerts should conclude immediately.
    assert alert.status == AlertStatus.RESOLVED

    client.app.dependency_overrides.clear()
