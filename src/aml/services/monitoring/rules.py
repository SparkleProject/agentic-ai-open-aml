import logging
from decimal import Decimal
from typing import Any, ClassVar

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition, RuleMatch

logger = logging.getLogger(__name__)


class RuleEngine:
    def evaluate(self, transaction: dict[str, Any], rules: list[MonitoringRule]) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        for rule in rules:
            if not rule.enabled:
                continue
            if self._all_conditions_match(transaction, rule.conditions):
                matches.append(
                    RuleMatch(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        alert_type=rule.alert_type,
                        severity=rule.severity,
                        matched_conditions=[f"{c.field} {c.operator} {c.value}" for c in rule.conditions],
                    )
                )
        return matches

    def load_default_rules(self) -> list[MonitoringRule]:
        return RulePacks.general()

    def load_rules_for_entity_type(self, entity_type: str) -> list[MonitoringRule]:
        return RulePacks.for_entity_type(entity_type)

    def _all_conditions_match(self, transaction: dict[str, Any], conditions: list[RuleCondition]) -> bool:
        return all(self._evaluate_condition(transaction, c) for c in conditions)

    def _evaluate_condition(self, transaction: dict[str, Any], condition: RuleCondition) -> bool:
        field_value = self._resolve_field(transaction, condition.field)
        if field_value is None:
            return False

        target = condition.value
        op = condition.operator

        try:
            if op == "gt":
                return Decimal(str(field_value)) > Decimal(str(target))
            if op == "gte":
                return Decimal(str(field_value)) >= Decimal(str(target))
            if op == "lt":
                return Decimal(str(field_value)) < Decimal(str(target))
            if op == "lte":
                return Decimal(str(field_value)) <= Decimal(str(target))
            if op == "eq":
                return str(field_value) == str(target)
            if op == "in":
                return str(field_value) in [str(v) for v in target]
            if op == "contains":
                return str(target).lower() in str(field_value).lower()
        except (TypeError, ValueError, ArithmeticError):
            logger.warning("Condition evaluation failed: %s %s %s", condition.field, op, target)
            return False

        return False

    @staticmethod
    def _resolve_field(transaction: dict[str, Any], field_path: str) -> Any:
        if "." not in field_path:
            return transaction.get(field_path)

        parts = field_path.split(".", 1)
        parent = transaction.get(parts[0])
        if not isinstance(parent, dict):
            return None
        return parent.get(parts[1])


class RulePacks:
    _PACKS: ClassVar[dict[str, str]] = {
        "real_estate": "_real_estate",
        "legal": "_legal",
        "accounting": "_accounting",
    }

    @classmethod
    def general(cls) -> list[MonitoringRule]:
        return [
            MonitoringRule(
                id="STD-001",
                name="Threshold Reporting",
                description="Cash deposits >= $10,000 (AUSTRAC threshold reporting)",
                conditions=[
                    RuleCondition(field="amount", operator="gte", value=10000),
                    RuleCondition(field="direction", operator="eq", value="inbound"),
                ],
                alert_type="threshold_reporting",
                severity=AlertSeverity.MEDIUM,
            ),
            MonitoringRule(
                id="STD-002",
                name="High-Value Wire",
                description="Outbound wires >= $50,000",
                conditions=[
                    RuleCondition(field="amount", operator="gte", value=50000),
                    RuleCondition(field="direction", operator="eq", value="outbound"),
                ],
                alert_type="high_value_wire",
                severity=AlertSeverity.HIGH,
            ),
            MonitoringRule(
                id="STD-003",
                name="High-Risk Jurisdiction",
                description="Transactions involving high-risk country counterparties",
                conditions=[
                    RuleCondition(field="counterparty", operator="contains", value="high_risk"),
                ],
                alert_type="high_risk_jurisdiction",
                severity=AlertSeverity.HIGH,
            ),
        ]

    @classmethod
    def for_entity_type(cls, entity_type: str) -> list[MonitoringRule]:
        method_name = cls._PACKS.get(entity_type)
        if not method_name:
            return []
        return getattr(cls, method_name)()

    @classmethod
    def _real_estate(cls) -> list[MonitoringRule]:
        return [
            MonitoringRule(
                id="T2RE-001",
                name="Cash Property Purchase",
                description="Cash settlement >= $10,000",
                conditions=[
                    RuleCondition(field="metadata_.settlement_type", operator="eq", value="cash"),
                    RuleCondition(field="amount", operator="gte", value=10000),
                ],
                alert_type="cash_property_purchase",
                severity=AlertSeverity.HIGH,
                entity_type="real_estate",
            ),
            MonitoringRule(
                id="T2RE-002",
                name="Nominee Purchaser",
                description="Purchaser flagged as nominee",
                conditions=[
                    RuleCondition(field="metadata_.purchaser_type", operator="eq", value="nominee"),
                ],
                alert_type="nominee_purchaser",
                severity=AlertSeverity.HIGH,
                entity_type="real_estate",
            ),
            MonitoringRule(
                id="T2RE-004",
                name="Unexplained Fund Source",
                description="High-value transaction with no documented fund source",
                conditions=[
                    RuleCondition(field="amount", operator="gte", value=50000),
                    RuleCondition(field="metadata_.fund_source", operator="eq", value="unknown"),
                ],
                alert_type="unexplained_fund_source",
                severity=AlertSeverity.MEDIUM,
                entity_type="real_estate",
            ),
        ]

    @classmethod
    def _legal(cls) -> list[MonitoringRule]:
        return [
            MonitoringRule(
                id="T2LG-001",
                name="Trust Account Cash Deposit",
                description="Inbound cash >= $10,000 to trust account",
                conditions=[
                    RuleCondition(field="metadata_.trust_account", operator="eq", value="True"),
                    RuleCondition(field="direction", operator="eq", value="inbound"),
                    RuleCondition(field="amount", operator="gte", value=10000),
                ],
                alert_type="trust_cash_deposit",
                severity=AlertSeverity.HIGH,
                entity_type="legal",
            ),
            MonitoringRule(
                id="T2LG-003",
                name="Overseas Fund Source",
                description="Funds from overseas >= $5,000",
                conditions=[
                    RuleCondition(field="metadata_.fund_source", operator="eq", value="overseas"),
                    RuleCondition(field="amount", operator="gte", value=5000),
                ],
                alert_type="overseas_fund_source",
                severity=AlertSeverity.MEDIUM,
                entity_type="legal",
            ),
            MonitoringRule(
                id="T2LG-004",
                name="Cash Payment for Legal Fees",
                description="Cash fee payment >= $5,000",
                conditions=[
                    RuleCondition(field="metadata_.payment_type", operator="eq", value="cash"),
                    RuleCondition(field="direction", operator="eq", value="inbound"),
                    RuleCondition(field="amount", operator="gte", value=5000),
                ],
                alert_type="cash_legal_fees",
                severity=AlertSeverity.MEDIUM,
                entity_type="legal",
            ),
        ]

    @classmethod
    def _accounting(cls) -> list[MonitoringRule]:
        return [
            MonitoringRule(
                id="T2AC-001",
                name="Inter-Entity Layering Indicator",
                description="Transaction with 3+ entity chain",
                conditions=[
                    RuleCondition(field="metadata_.entity_chain_length", operator="gte", value=3),
                ],
                alert_type="inter_entity_layering",
                severity=AlertSeverity.HIGH,
                entity_type="accounting",
            ),
            MonitoringRule(
                id="T2AC-002",
                name="Unusual Refund Pattern",
                description="Large refund >= $10,000",
                conditions=[
                    RuleCondition(field="metadata_.type", operator="eq", value="refund"),
                    RuleCondition(field="direction", operator="eq", value="inbound"),
                    RuleCondition(field="amount", operator="gte", value=10000),
                ],
                alert_type="unusual_refund",
                severity=AlertSeverity.MEDIUM,
                entity_type="accounting",
            ),
            MonitoringRule(
                id="T2AC-003",
                name="Complex Offshore Structure",
                description="Entity chain includes offshore jurisdiction",
                conditions=[
                    RuleCondition(field="metadata_.offshore_entities", operator="eq", value="True"),
                ],
                alert_type="offshore_structure",
                severity=AlertSeverity.HIGH,
                entity_type="accounting",
            ),
        ]
