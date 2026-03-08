"""
FastAPI health-check router.

Provides /health (liveness) and /ready (readiness) endpoints.
Kubernetes and Docker health checks hit these to determine if the service is up.
"""

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — is the process alive?"""
    return {"status": "ok"}


@router.get("/ready")
async def readiness() -> dict[str, Any]:
    """
    Readiness probe — can the service handle traffic?

    TODO (Phase 1): Check database, Redis, and vector DB connectivity.
    """
    return {
        "status": "ok",
        "checks": {
            "database": "not_configured",
            "redis": "not_configured",
            "vector_db": "not_configured",
        },
    }
