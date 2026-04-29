"""
Generic CRUD operations for tenant-scoped models.

Every query automatically filters by ``tenant_id`` so one tenant
can never read or modify another tenant's data.
"""

import uuid
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.base import Base

T = TypeVar("T", bound=Base)


async def create[T: Base](
    session: AsyncSession,
    model: type[T],
    *,
    tenant_id: str,
    **kwargs: Any,
) -> T:
    """Create a new record for the given tenant."""
    obj = model(tenant_id=tenant_id, **kwargs)
    session.add(obj)
    await session.flush()
    await session.refresh(obj)
    return obj


async def get_by_id[T: Base](
    session: AsyncSession,
    model: type[T],
    *,
    record_id: uuid.UUID,
    tenant_id: str,
) -> T | None:
    """Fetch one record by ID, scoped to tenant."""
    stmt = select(model).where(
        model.id == record_id,
        model.tenant_id == tenant_id,  # type: ignore[attr-defined]
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_tenant[T: Base](
    session: AsyncSession,
    model: type[T],
    *,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[T]:
    """List records belonging to a tenant with pagination."""
    stmt = (
        select(model)
        .where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
        .order_by(model.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update[T: Base](
    session: AsyncSession,
    obj: T,
    **kwargs: Any,
) -> T:
    """Update fields on an existing record."""
    for key, value in kwargs.items():
        setattr(obj, key, value)
    await session.flush()
    await session.refresh(obj)
    return obj


async def delete[T: Base](
    session: AsyncSession,
    obj: T,
) -> None:
    """Delete a record."""
    await session.delete(obj)
    await session.flush()
