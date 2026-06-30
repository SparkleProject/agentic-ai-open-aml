import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.transaction import Transaction
from aml.services.monitoring.rules import RuleEngine
from aml.services.monitoring.schemas import MonitoringRule


@dataclass
class DryRunMatch:
    transaction_id: str
    matched_conditions: list[str]


@dataclass
class DryRunResult:
    rule_id: str
    transactions_scanned: int
    match_count: int
    matches: list[DryRunMatch] = field(default_factory=list)
    execution_time_ms: float = 0.0


class RuleDryRunService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        rule_engine: RuleEngine | None = None,
    ) -> None:
        self._session = session
        self._engine = rule_engine or RuleEngine()

    async def dry_run(
        self,
        *,
        tenant_id: str,
        rule: MonitoringRule,
        days_back: int = 30,
        limit: int = 1000,
    ) -> DryRunResult:
        start = time.monotonic()

        cutoff = datetime.now(tz=UTC) - timedelta(days=days_back)
        stmt = (
            select(Transaction)
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.transaction_date >= cutoff,
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        transactions = result.scalars().all()

        matches: list[DryRunMatch] = []
        for tx in transactions:
            tx_dict: dict[str, Any] = {
                "amount": tx.amount,
                "currency": tx.currency,
                "direction": tx.direction.value if hasattr(tx.direction, "value") else tx.direction,
                "counterparty": tx.counterparty,
                "description": tx.description,
                "metadata_": tx.metadata_ or {},
            }
            rule_matches = self._engine.evaluate(tx_dict, [rule])
            if rule_matches:
                matches.append(
                    DryRunMatch(
                        transaction_id=str(tx.id),
                        matched_conditions=rule_matches[0].matched_conditions,
                    )
                )

        elapsed = (time.monotonic() - start) * 1000

        return DryRunResult(
            rule_id=rule.id,
            transactions_scanned=len(transactions),
            match_count=len(matches),
            matches=matches,
            execution_time_ms=round(elapsed, 2),
        )
