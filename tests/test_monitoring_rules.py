"""Tests for the monitoring rule engine (BE-206 Step 1)."""

from decimal import Decimal

import pytest

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.rules import RuleEngine
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition

# ---------------------------------------------------------------------------
# RuleCondition / MonitoringRule schema validation
# ---------------------------------------------------------------------------


class TestRuleSchemaValidation:
    def test_rule_condition_creation(self):
        cond = RuleCondition(field="amount", operator="gte", value=10000)
        assert cond.field == "amount"
        assert cond.operator == "gte"
        assert cond.value == 10000

    def test_rule_condition_rejects_invalid_operator(self):
        with pytest.raises(ValueError):
            RuleCondition(field="amount", operator="INVALID", value=10000)

    def test_monitoring_rule_creation(self):
        rule = MonitoringRule(
            id="STD-001",
            name="Threshold Reporting",
            description="Cash deposits >= $10,000",
            conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
            alert_type="threshold_reporting",
            severity=AlertSeverity.MEDIUM,
        )
        assert rule.id == "STD-001"
        assert rule.enabled is True
        assert len(rule.conditions) == 1

    def test_monitoring_rule_defaults_enabled(self):
        rule = MonitoringRule(
            id="R1",
            name="Test",
            description="Test rule",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        assert rule.enabled is True

    def test_monitoring_rule_can_be_disabled(self):
        rule = MonitoringRule(
            id="R1",
            name="Test",
            description="Test rule",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
            enabled=False,
        )
        assert rule.enabled is False


# ---------------------------------------------------------------------------
# RuleEngine.evaluate — operator tests
# ---------------------------------------------------------------------------


class TestRuleEngineEvaluate:
    def _make_transaction_dict(self, **overrides):
        base = {
            "amount": Decimal("5000.00"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
            "description": "Invoice payment",
        }
        base.update(overrides)
        return base

    def test_gte_operator_matches(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Large deposit",
            description="Amount >= 10000",
            conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
            alert_type="large_deposit",
            severity=AlertSeverity.MEDIUM,
        )
        tx = self._make_transaction_dict(amount=Decimal("15000.00"))
        matches = engine.evaluate(tx, [rule])
        assert len(matches) == 1
        assert matches[0].rule_id == "R1"

    def test_gte_operator_no_match_when_below(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Large deposit",
            description="Amount >= 10000",
            conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
            alert_type="large_deposit",
            severity=AlertSeverity.MEDIUM,
        )
        tx = self._make_transaction_dict(amount=Decimal("9999.99"))
        matches = engine.evaluate(tx, [rule])
        assert len(matches) == 0

    def test_gt_operator(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Over 50k",
            description="Amount > 50000",
            conditions=[RuleCondition(field="amount", operator="gt", value=50000)],
            alert_type="high_value",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(amount=Decimal("50001"))
        tx_no = self._make_transaction_dict(amount=Decimal("50000"))
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_lt_operator(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Micro tx",
            description="Amount < 100",
            conditions=[RuleCondition(field="amount", operator="lt", value=100)],
            alert_type="micro_tx",
            severity=AlertSeverity.LOW,
        )
        tx_match = self._make_transaction_dict(amount=Decimal("99.99"))
        tx_no = self._make_transaction_dict(amount=Decimal("100"))
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_lte_operator(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="At or below",
            description="Amount <= 100",
            conditions=[RuleCondition(field="amount", operator="lte", value=100)],
            alert_type="at_or_below",
            severity=AlertSeverity.LOW,
        )
        tx_match = self._make_transaction_dict(amount=Decimal("100"))
        tx_no = self._make_transaction_dict(amount=Decimal("101"))
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_eq_operator_string(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Inbound only",
            description="Direction == inbound",
            conditions=[RuleCondition(field="direction", operator="eq", value="inbound")],
            alert_type="inbound_only",
            severity=AlertSeverity.LOW,
        )
        tx_match = self._make_transaction_dict(direction="inbound")
        tx_no = self._make_transaction_dict(direction="outbound")
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_in_operator(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="High-risk currency",
            description="Currency in high-risk list",
            conditions=[RuleCondition(field="currency", operator="in", value=["IRR", "KPW", "SYP"])],
            alert_type="high_risk_currency",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(currency="IRR")
        tx_no = self._make_transaction_dict(currency="AUD")
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_contains_operator(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Shell company",
            description="Counterparty contains 'shell'",
            conditions=[RuleCondition(field="counterparty", operator="contains", value="shell")],
            alert_type="shell_company",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(counterparty="Acme Shell Co")
        tx_no = self._make_transaction_dict(counterparty="Legitimate Corp")
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_multiple_conditions_all_must_match(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Large inbound",
            description="Amount >= 10000 AND direction == inbound",
            conditions=[
                RuleCondition(field="amount", operator="gte", value=10000),
                RuleCondition(field="direction", operator="eq", value="inbound"),
            ],
            alert_type="large_inbound",
            severity=AlertSeverity.MEDIUM,
        )
        tx_both = self._make_transaction_dict(amount=Decimal("15000"), direction="inbound")
        tx_amount_only = self._make_transaction_dict(amount=Decimal("15000"), direction="outbound")
        tx_dir_only = self._make_transaction_dict(amount=Decimal("5000"), direction="inbound")

        assert len(engine.evaluate(tx_both, [rule])) == 1
        assert len(engine.evaluate(tx_amount_only, [rule])) == 0
        assert len(engine.evaluate(tx_dir_only, [rule])) == 0

    def test_disabled_rule_is_skipped(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Disabled",
            description="Should be skipped",
            conditions=[RuleCondition(field="amount", operator="gte", value=0)],
            alert_type="should_not_fire",
            severity=AlertSeverity.LOW,
            enabled=False,
        )
        tx = self._make_transaction_dict()
        assert len(engine.evaluate(tx, [rule])) == 0

    def test_multiple_rules_can_match(self):
        engine = RuleEngine()
        rule_a = MonitoringRule(
            id="RA",
            name="Rule A",
            description="Amount >= 1000",
            conditions=[RuleCondition(field="amount", operator="gte", value=1000)],
            alert_type="type_a",
            severity=AlertSeverity.LOW,
        )
        rule_b = MonitoringRule(
            id="RB",
            name="Rule B",
            description="Direction inbound",
            conditions=[RuleCondition(field="direction", operator="eq", value="inbound")],
            alert_type="type_b",
            severity=AlertSeverity.MEDIUM,
        )
        tx = self._make_transaction_dict(amount=Decimal("5000"), direction="inbound")
        matches = engine.evaluate(tx, [rule_a, rule_b])
        assert len(matches) == 2
        rule_ids = {m.rule_id for m in matches}
        assert rule_ids == {"RA", "RB"}

    def test_rule_match_carries_correct_metadata(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="STD-001",
            name="Threshold Reporting",
            description="Cash deposits >= $10,000",
            conditions=[RuleCondition(field="amount", operator="gte", value=10000)],
            alert_type="threshold_reporting",
            severity=AlertSeverity.MEDIUM,
        )
        tx = self._make_transaction_dict(amount=Decimal("12000"))
        matches = engine.evaluate(tx, [rule])
        match = matches[0]
        assert match.rule_id == "STD-001"
        assert match.rule_name == "Threshold Reporting"
        assert match.alert_type == "threshold_reporting"
        assert match.severity == AlertSeverity.MEDIUM

    def test_missing_field_does_not_crash(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Check nonexistent",
            description="Field that does not exist",
            conditions=[RuleCondition(field="nonexistent_field", operator="eq", value="x")],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        tx = self._make_transaction_dict()
        matches = engine.evaluate(tx, [rule])
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# RuleEngine.load_default_rules — built-in rule set
# ---------------------------------------------------------------------------


class TestMetadotFieldAccess:
    """Test dotted field paths like 'metadata_.trust_account' for Tranche 2 rules."""

    def _make_transaction_dict(self, **overrides):
        base = {
            "amount": Decimal("5000.00"),
            "currency": "AUD",
            "direction": "inbound",
            "counterparty": "Acme Corp",
            "metadata_": {},
        }
        base.update(overrides)
        return base

    def test_dotted_field_matches_metadata(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="T2LG-001",
            name="Trust Account Cash Deposit",
            description="Trust account inbound >= $10,000",
            conditions=[
                RuleCondition(field="metadata_.trust_account", operator="eq", value="True"),
                RuleCondition(field="amount", operator="gte", value=10000),
            ],
            alert_type="trust_cash_deposit",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(
            amount=Decimal("15000"),
            metadata_={"trust_account": True},
        )
        tx_no_meta = self._make_transaction_dict(
            amount=Decimal("15000"),
            metadata_={},
        )
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no_meta, [rule])) == 0

    def test_dotted_field_settlement_type(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="T2RE-001",
            name="Cash Property Purchase",
            description="Cash settlement >= $10,000",
            conditions=[
                RuleCondition(field="metadata_.settlement_type", operator="eq", value="cash"),
                RuleCondition(field="amount", operator="gte", value=10000),
            ],
            alert_type="cash_property_purchase",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(
            amount=Decimal("250000"),
            metadata_={"settlement_type": "cash"},
        )
        tx_no = self._make_transaction_dict(
            amount=Decimal("250000"),
            metadata_={"settlement_type": "bank_transfer"},
        )
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0

    def test_dotted_field_missing_metadata_key_no_crash(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Check missing key",
            description="metadata_.nonexistent == x",
            conditions=[RuleCondition(field="metadata_.nonexistent", operator="eq", value="x")],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        tx = self._make_transaction_dict(metadata_={"other_key": "value"})
        assert len(engine.evaluate(tx, [rule])) == 0

    def test_dotted_field_none_metadata_no_crash(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="R1",
            name="Check null metadata",
            description="metadata_.key == x",
            conditions=[RuleCondition(field="metadata_.key", operator="eq", value="x")],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        tx = self._make_transaction_dict(metadata_=None)
        assert len(engine.evaluate(tx, [rule])) == 0

    def test_dotted_field_purchaser_type_nominee(self):
        engine = RuleEngine()
        rule = MonitoringRule(
            id="T2RE-002",
            name="Nominee Purchaser",
            description="Purchaser flagged as nominee",
            conditions=[RuleCondition(field="metadata_.purchaser_type", operator="eq", value="nominee")],
            alert_type="nominee_purchaser",
            severity=AlertSeverity.HIGH,
        )
        tx_match = self._make_transaction_dict(metadata_={"purchaser_type": "nominee"})
        tx_no = self._make_transaction_dict(metadata_={"purchaser_type": "direct"})
        assert len(engine.evaluate(tx_match, [rule])) == 1
        assert len(engine.evaluate(tx_no, [rule])) == 0


class TestMonitoringRuleEntityType:
    def test_rule_entity_type_defaults_none(self):
        rule = MonitoringRule(
            id="R1",
            name="Test",
            description="Test rule",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.LOW,
        )
        assert rule.entity_type is None

    def test_rule_entity_type_can_be_set(self):
        rule = MonitoringRule(
            id="T2RE-001",
            name="Real Estate Rule",
            description="Test",
            conditions=[],
            alert_type="test",
            severity=AlertSeverity.HIGH,
            entity_type="real_estate",
        )
        assert rule.entity_type == "real_estate"


class TestDefaultRules:
    def test_load_default_rules_returns_non_empty(self):
        engine = RuleEngine()
        rules = engine.load_default_rules()
        assert len(rules) >= 3

    def test_default_rules_include_threshold_reporting(self):
        engine = RuleEngine()
        rules = engine.load_default_rules()
        rule_ids = {r.id for r in rules}
        assert "STD-001" in rule_ids

    def test_all_default_rules_are_enabled(self):
        engine = RuleEngine()
        rules = engine.load_default_rules()
        for rule in rules:
            assert rule.enabled is True

    def test_all_default_rules_have_valid_severity(self):
        engine = RuleEngine()
        rules = engine.load_default_rules()
        for rule in rules:
            assert rule.severity in AlertSeverity


class TestTranche2RulePacks:
    def test_load_tranche2_real_estate_rules(self):
        engine = RuleEngine()
        rules = engine.load_rules_for_entity_type("real_estate")
        assert len(rules) >= 2
        assert all(r.entity_type == "real_estate" for r in rules)
        alert_types = {r.alert_type for r in rules}
        assert "cash_property_purchase" in alert_types
        assert "nominee_purchaser" in alert_types

    def test_load_tranche2_legal_rules(self):
        engine = RuleEngine()
        rules = engine.load_rules_for_entity_type("legal")
        assert len(rules) >= 2
        assert all(r.entity_type == "legal" for r in rules)
        alert_types = {r.alert_type for r in rules}
        assert "trust_cash_deposit" in alert_types

    def test_load_tranche2_accounting_rules(self):
        engine = RuleEngine()
        rules = engine.load_rules_for_entity_type("accounting")
        assert len(rules) >= 2
        assert all(r.entity_type == "accounting" for r in rules)
        alert_types = {r.alert_type for r in rules}
        assert "inter_entity_layering" in alert_types

    def test_load_unknown_entity_type_returns_empty(self):
        engine = RuleEngine()
        rules = engine.load_rules_for_entity_type("unknown_entity")
        assert len(rules) == 0

    def test_tranche2_rules_all_enabled(self):
        engine = RuleEngine()
        for entity_type in ("real_estate", "legal", "accounting"):
            rules = engine.load_rules_for_entity_type(entity_type)
            for rule in rules:
                assert rule.enabled is True
