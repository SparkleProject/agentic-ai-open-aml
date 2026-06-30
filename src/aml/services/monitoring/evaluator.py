from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.anomaly import AnomalyScorer, CustomerProfile
from aml.services.monitoring.rules import RuleEngine
from aml.services.monitoring.schemas import MonitoringRule

if TYPE_CHECKING:
    from aml.services.monitoring.rule_cache import RuleCache

ANOMALY_THRESHOLD_DEFAULT = 40.0


@dataclass
class AlertData:
    tenant_id: str
    customer_id: str
    alert_type: str
    severity: AlertSeverity
    title: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)


class TransactionEvaluator:
    def __init__(
        self,
        *,
        rule_engine: RuleEngine | None = None,
        anomaly_scorer: AnomalyScorer | None = None,
        anomaly_threshold: float = ANOMALY_THRESHOLD_DEFAULT,
        rule_cache: RuleCache | None = None,
    ) -> None:
        self._rule_engine = rule_engine or RuleEngine()
        self._anomaly_scorer = anomaly_scorer or AnomalyScorer()
        self._anomaly_threshold = anomaly_threshold
        self._rule_cache = rule_cache

    def evaluate(
        self,
        *,
        transaction: dict[str, Any],
        rules: list[MonitoringRule],
        profile: CustomerProfile,
        customer_id: str,
        tenant_id: str,
    ) -> list[AlertData]:
        alerts: list[AlertData] = []
        alerts.extend(self._evaluate_rules(transaction, rules, customer_id, tenant_id))
        alerts.extend(self._evaluate_anomaly(transaction, profile, customer_id, tenant_id))
        return alerts

    def _evaluate_rules(
        self,
        transaction: dict[str, Any],
        rules: list[MonitoringRule],
        customer_id: str,
        tenant_id: str,
    ) -> list[AlertData]:
        alerts: list[AlertData] = []
        for match in self._rule_engine.evaluate(transaction, rules):
            alerts.append(
                AlertData(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    alert_type=match.alert_type,
                    severity=match.severity,
                    title=f"Rule Match: {match.rule_name}",
                    description=f"Transaction matched rule {match.rule_id}: {', '.join(match.matched_conditions)}",
                    details={
                        "rule_id": match.rule_id,
                        "rule_name": match.rule_name,
                        "matched_conditions": match.matched_conditions,
                    },
                )
            )
        return alerts

    def _evaluate_anomaly(
        self,
        transaction: dict[str, Any],
        profile: CustomerProfile,
        customer_id: str,
        tenant_id: str,
    ) -> list[AlertData]:
        result = self._anomaly_scorer.score_transaction(
            amount=Decimal(str(transaction.get("amount", 0))),
            currency=str(transaction.get("currency", "")),
            counterparty=transaction.get("counterparty"),
            profile=profile,
        )

        if result.score < self._anomaly_threshold:
            return []

        return [
            AlertData(
                tenant_id=tenant_id,
                customer_id=customer_id,
                alert_type="anomaly_detection",
                severity=self._score_to_severity(result.score),
                title="Anomaly Detected",
                description=f"Anomaly score: {result.score:.1f}. Factors: {', '.join(result.factors)}",
                details={
                    "anomaly_score": result.score,
                    "factors": result.factors,
                },
            )
        ]

    async def evaluate_with_cache(
        self,
        *,
        transaction: dict[str, Any],
        tenant_id: str,
        customer_id: str,
        profile: CustomerProfile,
        entity_type: str | None = None,
    ) -> list[AlertData]:
        if self._rule_cache is None:
            raise RuntimeError("rule_cache not configured")
        rules = await self._rule_cache.get_rules(tenant_id=tenant_id, entity_type=entity_type)
        return self.evaluate(
            transaction=transaction,
            rules=rules,
            profile=profile,
            customer_id=customer_id,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _score_to_severity(score: float) -> AlertSeverity:
        if score >= 80:
            return AlertSeverity.CRITICAL
        if score >= 60:
            return AlertSeverity.HIGH
        if score >= 40:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW
