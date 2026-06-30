from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from aml.db.base import Base, TenantMixin
from aml.db.models.alert import AlertSeverity


class TenantRule(TenantMixin, Base):
    __tablename__ = "tenant_rules"

    tenant_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("tenants.id"),
        nullable=True,
        index=True,
    )

    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    alert_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, native_enum=False, length=20),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<TenantRule {self.rule_id} [{self.severity.value}] v{self.version}>"


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    tenant_rule_id: Mapped[str] = mapped_column(
        Uuid,
        ForeignKey("tenant_rules.id"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, native_enum=False, length=20),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)

    changed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<RuleVersion rule={self.tenant_rule_id} v{self.version}>"
