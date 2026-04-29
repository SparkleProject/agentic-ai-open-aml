"""Tenant model — the root entity in a multi-tenant system."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aml.db.base import Base

if TYPE_CHECKING:
    from aml.db.models.alert import Alert
    from aml.db.models.case import Case
    from aml.db.models.customer import Customer


class Tenant(Base):
    """
    A tenant (organisation) using the platform.

    Each tenant has isolated data, configurable risk appetite,
    and its own set of users, customers, and alerts.
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Flexible config: risk appetite, model preferences, thresholds
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    customers: Mapped[list["Customer"]] = relationship(back_populates="tenant", lazy="selectin")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="tenant", lazy="selectin")
    cases: Mapped[list["Case"]] = relationship(back_populates="tenant", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Tenant {self.slug}>"
