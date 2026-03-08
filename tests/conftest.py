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
        vector_db_provider="mock",
        log_format="console",
        log_level="DEBUG",
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """Synchronous test client for FastAPI."""
    app = create_app(settings=test_settings)
    return TestClient(app)
