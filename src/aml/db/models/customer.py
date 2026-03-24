"""Customer model — the entity being monitored for AML compliance."""

import enum

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aml.db.base import Base, TenantMixin


class CustomerType(enum.StrEnum):
    """Individual person vs. corporate entity."""

    INDIVIDUAL = "individual"
    ENTITY = "entity"


class RiskRating(enum.StrEnum):
    """Customer risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"


class Customer(TenantMixin, Base):
    """
    A customer being monitored for AML compliance.

    Belongs to a Tenant. Has transactions and may trigger alerts.
    """

    __tablename__ = "customers"

    # Foreign key back to tenant
    tenant: Mapped["Tenant"] = relationship(back_populates="customers")  # noqa: F821

    # Customer identity
    external_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="ID in the tenant's source system"
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    customer_type: Mapped[CustomerType] = mapped_column(
        SAEnum(CustomerType, native_enum=False, length=20),
        default=CustomerType.INDIVIDUAL,
    )

    # Risk
    risk_rating: Mapped[RiskRating] = mapped_column(
        SAEnum(RiskRating, native_enum=False, length=20),
        default=RiskRating.LOW,
    )

    # Flexible metadata (PEP status, nationality, DOB, etc.)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="customer", lazy="selectin")  # noqa: F821

    # Tenant FK (added explicitly so SQLAlchemy knows which column to join on)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Customer {self.name} ({self.external_id})>"
