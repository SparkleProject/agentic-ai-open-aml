"""
Tenant context middleware.

Extracts X-Tenant-ID from the request header and sets it in the
async context for downstream services.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from aml.core.context import clear_tenant_id, set_tenant_id


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract X-Tenant-ID header and populate tenant context."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            set_tenant_id(tenant_id)

        try:
            response = await call_next(request)
            # Echo the tenant ID back in the response for debugging
            if tenant_id:
                response.headers["X-Tenant-ID"] = tenant_id
            return response
        finally:
            clear_tenant_id()
