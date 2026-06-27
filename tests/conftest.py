"""
Test fixtures shared across the test suite.

Provides a test FastAPI client with overridden settings
so tests never hit real databases or external services.
"""

import pytest
from fastapi.testclient import TestClient

from aml.app import create_app
from aml.core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Settings overridden for testing — no external services needed."""
    return Settings(
        debug=True,
        environment="test",
        llm_provider="mock",
        embedding_provider="mock",
        vector_db_provider="mock",
        log_format="console",
        log_level="DEBUG",
    )


@pytest.fixture(autouse=True)
def reset_global_state(monkeypatch, test_settings):
    """Reset global/class variables between tests and monkeypatch get_settings globally."""
    import aml.agents.nodes
    import aml.api.routers.rag
    import aml.app
    import aml.core.config
    import aml.main
    import aml.services.triage.service
    from aml.services.llm.mock import MockLLMProvider

    # Reset LLM canned responses
    MockLLMProvider.canned_responses = []
    # Reset RAG service cache
    aml.api.routers.rag._rag_service = None

    # Patch get_settings in all namespaces that import it to prevent python from import reference copy issue
    for module in [
        aml.core.config,
        aml.app,
        aml.main,
        aml.services.triage.service,
        aml.api.routers.rag,
        aml.agents.nodes,
    ]:
        monkeypatch.setattr(module, "get_settings", lambda: test_settings)

    yield

    MockLLMProvider.canned_responses = []
    aml.api.routers.rag._rag_service = None


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """Synchronous test client for FastAPI."""
    app = create_app(settings=test_settings)
    return TestClient(app)
