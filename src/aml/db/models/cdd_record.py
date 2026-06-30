import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from aml.db.base import Base, TenantMixin


class CDDType(enum.StrEnum):
    INITIAL = "initial"
    ONGOING = "ongoing"
    ENHANCED = "enhanced"


class CDDStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    ESCALATED = "escalated"


class CDDRecord(TenantMixin, Base):
    __tablename__ = "cdd_records"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[str] = mapped_column(
        Uuid,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )

    cdd_type: Mapped[CDDType] = mapped_column(
        SAEnum(CDDType, native_enum=False, length=20),
        default=CDDType.INITIAL,
    )
    status: Mapped[CDDStatus] = mapped_column(
        SAEnum(CDDStatus, native_enum=False, length=20),
        default=CDDStatus.PENDING,
        index=True,
    )
    onboarding_stage: Mapped[str] = mapped_column(
        String(64),
        default="PENDING",
    )

    id_verification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pep_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sanctions_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    adverse_media_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    risk_assessment: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    overall_risk_score: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CDDRecord {self.cdd_type.value} [{self.status.value}] score={self.overall_risk_score}>"
