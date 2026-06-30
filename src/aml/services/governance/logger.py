import hashlib
import json
import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.governance_log import GovernanceLog

logger = structlog.get_logger()


@dataclass
class GovernanceEvent:
    tenant_id: str
    event_type: str
    agent_id: str
    input_summary: str = ""
    output_summary: str = ""
    status: str = "SUCCESS"
    case_id: str | None = None
    alert_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    system_prompt_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    temperature: float | None = None
    reasoning_chain: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GovernanceLogger:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session
        self._last_hash: dict[str, str] = {}

    async def log_event(self, event: GovernanceEvent) -> GovernanceLog:
        prev_hash = self._last_hash.get(event.tenant_id)
        content_hash = self._compute_hash(event, prev_hash)

        log_entry = GovernanceLog(
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            agent_id=event.agent_id,
            case_id=uuid_mod.UUID(event.case_id) if event.case_id else None,
            alert_id=uuid_mod.UUID(event.alert_id) if event.alert_id else None,
            model_id=event.model_id,
            model_version=event.model_version,
            system_prompt_hash=event.system_prompt_hash,
            input_summary=event.input_summary[:2000],
            output_summary=event.output_summary[:2000],
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            latency_ms=event.latency_ms,
            temperature=event.temperature,
            status=event.status,
            reasoning_chain=event.reasoning_chain,
            metadata_=event.metadata or None,
            content_hash=content_hash,
            prev_hash=prev_hash,
        )
        self._session.add(log_entry)
        await self._session.commit()
        self._last_hash[event.tenant_id] = content_hash

        logger.info(
            "governance_event_logged",
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            agent_id=event.agent_id,
        )
        return log_entry

    async def log_llm_invocation(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        model_id: str,
        prompt_summary: str,
        response_summary: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> GovernanceLog:
        return await self.log_event(
            GovernanceEvent(
                tenant_id=tenant_id,
                event_type="LLM_INVOCATION",
                agent_id=agent_id,
                model_id=model_id,
                input_summary=prompt_summary,
                output_summary=response_summary,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        )

    async def log_agent_decision(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        case_id: str | None = None,
        decision: str,
        reasoning: str | None = None,
    ) -> GovernanceLog:
        return await self.log_event(
            GovernanceEvent(
                tenant_id=tenant_id,
                event_type="AGENT_DECISION",
                agent_id=agent_id,
                case_id=case_id,
                output_summary=decision,
                reasoning_chain=reasoning,
            )
        )

    async def log_human_override(
        self,
        *,
        tenant_id: str,
        user_id: str,
        case_id: str,
        original_decision: str,
        override_decision: str,
        reason: str,
    ) -> GovernanceLog:
        return await self.log_event(
            GovernanceEvent(
                tenant_id=tenant_id,
                event_type="HUMAN_OVERRIDE",
                agent_id=user_id,
                case_id=case_id,
                input_summary=original_decision,
                output_summary=override_decision,
                reasoning_chain=reason,
            )
        )

    async def _get_prev_hash(self, tenant_id: str) -> str | None:
        stmt = (
            select(GovernanceLog.content_hash)
            .where(GovernanceLog.tenant_id == tenant_id)
            .order_by(GovernanceLog.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _compute_hash(event: GovernanceEvent, prev_hash: str | None) -> str:
        payload = json.dumps(
            {
                "tenant_id": event.tenant_id,
                "event_type": event.event_type,
                "agent_id": event.agent_id,
                "input": event.input_summary[:500],
                "output": event.output_summary[:500],
                "status": event.status,
                "prev_hash": prev_hash or "",
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
