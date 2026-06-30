import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.governance_log import GovernanceLog


@dataclass
class VerificationResult:
    is_valid: bool
    total_entries: int
    first_break_at: str | None = None
    error: str | None = None


class ChainVerifier:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def verify_chain(self, tenant_id: str) -> VerificationResult:
        stmt = select(GovernanceLog).where(GovernanceLog.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        all_entries = list(result.scalars().all())

        if not all_entries:
            return VerificationResult(is_valid=True, total_entries=0)

        entries_by_prev: dict[str | None, GovernanceLog] = {}
        for entry in all_entries:
            entries_by_prev[entry.prev_hash] = entry

        current = entries_by_prev.get(None)
        if not current:
            return VerificationResult(
                is_valid=False,
                total_entries=len(all_entries),
                error="No root entry found (prev_hash=None)",
            )

        verified = 0
        while current:
            expected = self._recompute_hash(current, current.prev_hash)
            if current.content_hash != expected:
                return VerificationResult(
                    is_valid=False,
                    total_entries=len(all_entries),
                    first_break_at=str(current.id),
                    error=f"content_hash mismatch at entry {current.id}",
                )
            verified += 1
            current = entries_by_prev.get(current.content_hash)

        return VerificationResult(is_valid=True, total_entries=verified)

    @staticmethod
    def _recompute_hash(entry: GovernanceLog, prev_hash: str | None) -> str:
        payload = json.dumps(
            {
                "tenant_id": entry.tenant_id,
                "event_type": entry.event_type,
                "agent_id": entry.agent_id,
                "input": entry.input_summary[:500],
                "output": entry.output_summary[:500],
                "status": entry.status,
                "prev_hash": prev_hash or "",
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
