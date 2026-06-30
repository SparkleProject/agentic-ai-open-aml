"""
Tenant context and authentication middleware.

Extracts JWT from Authorization header when present, falling back
to X-Tenant-ID header for backward compatibility.
"""

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from aml.core.config import get_settings
from aml.core.context import clear_tenant_id, set_tenant_id
from aml.services.auth.factory import get_auth_provider
from aml.services.auth.permissions import PermissionResolver

logger = structlog.get_logger()

PUBLIC_PATHS = {"/api/health", "/api/readiness", "/docs", "/redoc", "/openapi.json"}
PUBLIC_PREFIXES = ("/api/v1/auth/login", "/api/v1/auth/register")


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                settings = get_settings()
                provider = get_auth_provider(settings)
                payload = provider.verify_token(token)

                resolver = PermissionResolver()
                auth_context = resolver.resolve(payload.user_id, payload.tenant_id, payload.roles)
                request.state.auth = auth_context

                set_tenant_id(payload.tenant_id)
            except Exception:
                logger.debug("jwt_verification_failed", path=path)

        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            set_tenant_id(tenant_id)

        try:
            response = await call_next(request)
            current_tenant = request.headers.get("X-Tenant-ID")
            if current_tenant:
                response.headers["X-Tenant-ID"] = current_tenant
            return response
        finally:
            clear_tenant_id()
