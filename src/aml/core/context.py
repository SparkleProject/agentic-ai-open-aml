"""
Tenant context management via contextvars.

Provides request-scoped tenant isolation without passing tenant_id
through every function signature.
"""

from contextvars import ContextVar

_tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def set_tenant_id(tenant_id: str) -> None:
    """Set the tenant ID for the current async context."""
    _tenant_id_ctx.set(tenant_id)


def get_tenant_id() -> str | None:
    """Get the tenant ID from the current async context."""
    return _tenant_id_ctx.get()


def require_tenant_id() -> str:
    """Get the tenant ID or raise if not set (for endpoints that require it)."""
    tid = _tenant_id_ctx.get()
    if tid is None:
        msg = "X-Tenant-ID header is required"
        raise ValueError(msg)
    return tid


def clear_tenant_id() -> None:
    """Clear the tenant ID (called after request completes)."""
    _tenant_id_ctx.set(None)
