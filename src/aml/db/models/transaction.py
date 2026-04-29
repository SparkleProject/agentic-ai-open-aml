"""Transaction model — financial movements to monitor."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aml.db.base import Base, TenantMixin

if TYPE_CHECKING:
    from aml.db.models.customer import Customer


class TransactionDirection(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class Transaction(TenantMixin, Base):
    """
    A financial transaction linked to a customer.

    This is the core data that transaction monitoring rules
    and anomaly detection models operate on.
    """

    __tablename__ = "transactions"

    # Tenant FK
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )

    # Customer FK
    customer_id: Mapped[str] = mapped_column(
        Uuid,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )
    customer: Mapped["Customer"] = relationship(back_populates="transactions")

    # Transaction details
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NZD", nullable=False)
    direction: Mapped[TransactionDirection] = mapped_column(
        SAEnum(TransactionDirection, native_enum=False, length=20),
        nullable=False,
    )
    counterparty: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Flexible metadata (channel, geo, device, etc.)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Transaction {self.amount} {self.currency} {self.direction.value}>"
