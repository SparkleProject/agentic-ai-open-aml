"""
SQLAlchemy base model and mixins.

All database models inherit from ``Base``. Multi-tenant models
additionally use ``TenantMixin`` to get a ``tenant_id`` column
with an index — ready for Row-Level Security in production.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Declarative base for all ORM models.

    Every model gets:
    - ``id``: UUID primary key (server-generated)
    - ``created_at``: auto-set on insert
    - ``updated_at``: auto-set on insert and update
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """
    Marker mixin documenting that a model is tenant-scoped.

    Each model defines its own ``tenant_id`` mapped_column with a
    ``ForeignKey("tenants.id")`` so SQLAlchemy knows the join path.
    This mixin serves as documentation and a future hook for
    PostgreSQL Row-Level Security helpers.
    """
