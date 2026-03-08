"""
Tests for health check endpoints.

These are the first tests in the project — they validate that
the FastAPI app starts correctly and responds to basic requests.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestHealth:
    """Health endpoint tests."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """GET /api/health should return 200 with status ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_readiness_returns_checks(self, client: TestClient) -> None:
        """GET /api/ready should return 200 with service check statuses."""
        response = client.get("/api/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "checks" in data
        assert "database" in data["checks"]

    def test_request_id_header_injected(self, client: TestClient) -> None:
        """Every response should include an X-Request-ID header."""
        response = client.get("/api/health")
        assert "x-request-id" in response.headers

    def test_custom_request_id_echoed(self, client: TestClient) -> None:
        """If client sends X-Request-ID, it should be echoed back."""
        custom_id = "test-request-12345"
        response = client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert response.headers["x-request-id"] == custom_id
