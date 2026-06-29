import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aml.db.base import Base, TenantMixin

if TYPE_CHECKING:
    from aml.db.models.tenant import Tenant


class ReportStatus(enum.StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"


class Report(TenantMixin, Base):
    __tablename__ = "reports"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    tenant: Mapped["Tenant"] = relationship()

    case_id: Mapped[str | None] = mapped_column(
        Uuid,
        ForeignKey("cases.id"),
        nullable=True,
        index=True,
    )

    report_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus, native_enum=False, length=20),
        default=ReportStatus.DRAFT,
        index=True,
    )

    narrative: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Report {self.report_type} [{self.status.value}]>"
