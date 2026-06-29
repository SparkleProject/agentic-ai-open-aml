from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.evaluator import AlertData


@dataclass
class TransactionRecord:
    transaction_id: str
    customer_id: str
    tenant_id: str
    amount: Decimal
    currency: str
    direction: str
    counterparty: str | None
    transaction_date: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class BatchPatternScanner:
    def scan(
        self,
        *,
        transactions: list[TransactionRecord],
        tenant_id: str,  # noqa: ARG002
    ) -> list[AlertData]:
        alerts: list[AlertData] = []

        by_customer: dict[str, list[TransactionRecord]] = defaultdict(list)
        for tx in transactions:
            by_customer[tx.customer_id].append(tx)

        for _customer_id, customer_txs in by_customer.items():
            alerts.extend(
                self.detect_structuring(
                    transactions=customer_txs,
                    threshold=Decimal("10000"),
                    min_count=3,
                    lower_bound_ratio=0.8,
                )
            )
            alerts.extend(
                self.detect_velocity(
                    transactions=customer_txs,
                    window_hours=24,
                    threshold_count=10,
                )
            )
            alerts.extend(
                self.detect_round_trip(
                    transactions=customer_txs,
                    tolerance_ratio=0.05,
                )
            )

        return alerts

    def detect_structuring(
        self,
        *,
        transactions: list[TransactionRecord],
        threshold: Decimal,
        min_count: int,
        lower_bound_ratio: float,
    ) -> list[AlertData]:
        lower_bound = threshold * Decimal(str(lower_bound_ratio))
        suspect = [tx for tx in transactions if lower_bound <= tx.amount < threshold]

        if len(suspect) < min_count:
            return []

        customer_id = transactions[0].customer_id
        tenant_id = transactions[0].tenant_id
        tx_ids = [tx.transaction_id for tx in suspect]
        total = sum(tx.amount for tx in suspect)

        return [
            AlertData(
                tenant_id=tenant_id,
                customer_id=customer_id,
                alert_type="structuring",
                severity=AlertSeverity.HIGH,
                title=f"Potential structuring: {len(suspect)} sub-threshold transactions",
                description=(
                    f"{len(suspect)} transactions between {lower_bound} and {threshold} "
                    f"totaling {total} detected within the scan window."
                ),
                details={
                    "transaction_ids": tx_ids,
                    "count": len(suspect),
                    "total_amount": str(total),
                    "threshold": str(threshold),
                },
            )
        ]

    def detect_velocity(
        self,
        *,
        transactions: list[TransactionRecord],
        window_hours: int,
        threshold_count: int,
    ) -> list[AlertData]:
        cutoff = datetime.now(tz=UTC) - timedelta(hours=window_hours)
        recent = [tx for tx in transactions if tx.transaction_date >= cutoff]

        if len(recent) < threshold_count:
            return []

        customer_id = transactions[0].customer_id
        tenant_id = transactions[0].tenant_id

        return [
            AlertData(
                tenant_id=tenant_id,
                customer_id=customer_id,
                alert_type="rapid_velocity",
                severity=AlertSeverity.MEDIUM,
                title=f"High transaction velocity: {len(recent)} in {window_hours}h",
                description=(
                    f"{len(recent)} transactions within the last {window_hours} hours (threshold: {threshold_count})."
                ),
                details={
                    "transaction_count": len(recent),
                    "window_hours": window_hours,
                    "threshold": threshold_count,
                },
            )
        ]

    def detect_round_trip(
        self,
        *,
        transactions: list[TransactionRecord],
        tolerance_ratio: float,
    ) -> list[AlertData]:
        outbound = [tx for tx in transactions if tx.direction == "outbound"]
        inbound = [tx for tx in transactions if tx.direction == "inbound"]

        alerts: list[AlertData] = []

        for out_tx in outbound:
            for in_tx in inbound:
                if (
                    out_tx.counterparty
                    and out_tx.counterparty == in_tx.counterparty
                    and in_tx.transaction_date > out_tx.transaction_date
                ):
                    diff = abs(out_tx.amount - in_tx.amount)
                    if diff <= out_tx.amount * Decimal(str(tolerance_ratio)):
                        customer_id = transactions[0].customer_id
                        tenant_id = transactions[0].tenant_id
                        alerts.append(
                            AlertData(
                                tenant_id=tenant_id,
                                customer_id=customer_id,
                                alert_type="round_trip",
                                severity=AlertSeverity.HIGH,
                                title=f"Potential round-trip with {out_tx.counterparty}",
                                description=(
                                    f"Outbound {out_tx.amount} followed by inbound {in_tx.amount} "
                                    f"from same counterparty {out_tx.counterparty}."
                                ),
                                details={
                                    "outbound_tx": out_tx.transaction_id,
                                    "inbound_tx": in_tx.transaction_id,
                                    "outbound_amount": str(out_tx.amount),
                                    "inbound_amount": str(in_tx.amount),
                                    "counterparty": out_tx.counterparty,
                                },
                            )
                        )

        return alerts

    # ------------------------------------------------------------------
    # Tranche 2 batch patterns
    # ------------------------------------------------------------------

    def detect_trust_account_anomaly(
        self,
        *,
        transactions: list[TransactionRecord],
        client_list: set[str],
        min_count: int,
    ) -> list[AlertData]:
        trust_txs = [tx for tx in transactions if tx.metadata.get("trust_account") is True]

        non_client = [tx for tx in trust_txs if tx.counterparty and tx.counterparty not in client_list]

        if len(non_client) < min_count:
            return []

        customer_id = transactions[0].customer_id
        tenant_id = transactions[0].tenant_id
        tx_ids = [tx.transaction_id for tx in non_client]
        sources = list({tx.counterparty for tx in non_client if tx.counterparty})

        return [
            AlertData(
                tenant_id=tenant_id,
                customer_id=customer_id,
                alert_type="non_client_trust_funds",
                severity=AlertSeverity.HIGH,
                title=f"Trust account received funds from {len(sources)} non-client source(s)",
                description=(
                    f"{len(non_client)} trust account deposits from counterparties not in client list: "
                    f"{', '.join(sources[:5])}"
                ),
                details={
                    "transaction_ids": tx_ids,
                    "non_client_sources": sources,
                    "count": len(non_client),
                },
            )
        ]

    def detect_inter_entity_layering(
        self,
        *,
        transactions: list[TransactionRecord],
        min_chain_length: int,
    ) -> list[AlertData]:
        suspect = [
            tx
            for tx in transactions
            if isinstance(tx.metadata.get("entity_chain"), list)
            and len(tx.metadata["entity_chain"]) >= min_chain_length
        ]

        if not suspect:
            return []

        customer_id = transactions[0].customer_id
        tenant_id = transactions[0].tenant_id
        tx_ids = [tx.transaction_id for tx in suspect]
        all_entities: set[str] = set()
        for tx in suspect:
            all_entities.update(tx.metadata["entity_chain"])

        return [
            AlertData(
                tenant_id=tenant_id,
                customer_id=customer_id,
                alert_type="inter_entity_layering",
                severity=AlertSeverity.HIGH,
                title=f"Inter-entity layering: {len(all_entities)} entities across {len(suspect)} transactions",
                description=(
                    f"{len(suspect)} transaction(s) involve entity chains of {min_chain_length}+ entities: "
                    f"{', '.join(sorted(all_entities)[:10])}"
                ),
                details={
                    "transaction_ids": tx_ids,
                    "entities_involved": sorted(all_entities),
                    "count": len(suspect),
                },
            )
        ]
