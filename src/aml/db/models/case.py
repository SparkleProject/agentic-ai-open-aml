"""Case model — investigation container created from alerts."""

import enum

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aml.db.base import Base, TenantMixin


class CaseStatus(enum.StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_REVIEW = "pending_review"
    CLOSED_NO_ACTION = "closed_no_action"
    CLOSED_SAR_FILED = "closed_sar_filed"


class Case(TenantMixin, Base):
    """
    An investigation case — created when an alert warrants deeper analysis.

    The ``reasoning`` JSONB column stores the full agent XAI trace:
    every observation, tool call, and conclusion the agent made.
    This is the explainability backbone for ISO 42001 compliance.
    """

    __tablename__ = "cases"

    # Tenant FK
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    tenant: Mapped["Tenant"] = relationship(back_populates="cases")  # noqa: F821

    # Linked alert
    alert_id: Mapped[str | None] = mapped_column(
        Uuid,
        ForeignKey("alerts.id"),
        nullable=True,
        index=True,
    )

    # Case workflow
    status: Mapped[CaseStatus] = mapped_column(
        SAEnum(CaseStatus, native_enum=False, length=30),
        default=CaseStatus.OPEN,
        index=True,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Investigation content
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # XAI reasoning chain — stores the full agent trace
    reasoning: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Case {self.id} [{self.status.value}]>"
