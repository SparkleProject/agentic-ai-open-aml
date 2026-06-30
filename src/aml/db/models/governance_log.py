from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aml.db.base import Base


class GovernanceLog(Base):
    __tablename__ = "governance_logs"

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)

    case_id: Mapped[str | None] = mapped_column(Uuid, nullable=True)
    alert_id: Mapped[str | None] = mapped_column(Uuid, nullable=True)

    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    input_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUCCESS")
    reasoning_chain: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<GovernanceLog {self.event_type} [{self.status}]>"
