"""
FastAPI application factory.

Creates and configures the FastAPI app with:
- Structured logging
- CORS middleware
- Request ID middleware (for tracing)
- API routers (health, future: alerts, cases, agents)
- Lifespan management (startup/shutdown hooks)
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from aml.api.health import router as health_router
from aml.api.middleware import TenantMiddleware
from aml.core.config import Settings, get_settings
from aml.core.context import get_tenant_id
from aml.core.logging import setup_logging

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifecycle.

    Startup: initialise DB connections, caches, vector DB clients.
    Shutdown: close connections gracefully.
    """
    settings = get_settings()
    setup_logging(settings)
    await logger.ainfo("application_starting", environment=settings.environment)

    # Initialise database connection pool
    from aml.db.session import close_db, init_db

    init_db(settings)
    await logger.ainfo("database_initialised")

    # TODO (Phase 1): Initialise Redis client
    # TODO (Phase 2): Initialise vector DB client

    yield

    # Shutdown
    await logger.ainfo("application_shutting_down")
    await close_db()
    # TODO (Phase 1): Close Redis connection


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Application factory.

    Why a factory? So we can create separate app instances for testing
    with overridden settings, without polluting the global state.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Open-source Agentic AI platform for AML compliance",
        docs_url="/docs" if settings.debug else None,  # Disable Swagger in production
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # --- Middleware ---

    # CORS — permissive in dev, locked down in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.environment == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID middleware — injects a unique ID into every request for tracing
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: ...) -> Response:  # type: ignore[type-arg]
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        # Bind tenant_id if set by TenantMiddleware
        tenant_id = get_tenant_id()
        if tenant_id:
            structlog.contextvars.bind_contextvars(tenant_id=tenant_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Tenant context middleware (runs before request_id middleware in Starlette stack)
    app.add_middleware(TenantMiddleware)

    # --- Routers ---
    app.include_router(health_router, prefix="/api")

    from aml.api.routers.rag import router as rag_router

    app.include_router(rag_router, prefix="/api/v1")

    # TODO (Phase 2): app.include_router(alerts_router, prefix="/api/v1")
    # TODO (Phase 2): app.include_router(agents_router, prefix="/api/v1")
    # TODO (Phase 3): app.include_router(reports_router, prefix="/api/v1")

    return app
