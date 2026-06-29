"""Tests for the batch pattern scanner (BE-206 Step 4)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.batch import BatchPatternScanner, TransactionRecord


@pytest.fixture
def scanner():
    return BatchPatternScanner()


def _tx(
    *,
    customer_id: str = "cust-001",
    amount: Decimal = Decimal("5000"),
    direction: str = "inbound",
    counterparty: str = "Acme Corp",
    hours_ago: float = 1.0,
    metadata: dict | None = None,
) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=f"tx-{id(amount)}-{hours_ago}",
        customer_id=customer_id,
        tenant_id="tenant-001",
        amount=amount,
        currency="AUD",
        direction=direction,
        counterparty=counterparty,
        transaction_date=datetime.now(tz=UTC) - timedelta(hours=hours_ago),
        metadata=metadata or {},
    )


class TestStructuringDetection:
    def test_detects_structuring_pattern(self, scanner):
        transactions = [
            _tx(amount=Decimal("9500"), hours_ago=1),
            _tx(amount=Decimal("9800"), hours_ago=5),
            _tx(amount=Decimal("9200"), hours_ago=10),
        ]
        alerts = scanner.detect_structuring(
            transactions=transactions,
            threshold=Decimal("10000"),
            min_count=3,
            lower_bound_ratio=0.8,
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == "structuring"
        assert alerts[0].severity == AlertSeverity.HIGH

    def test_no_structuring_when_below_min_count(self, scanner):
        transactions = [
            _tx(amount=Decimal("9500"), hours_ago=1),
            _tx(amount=Decimal("9800"), hours_ago=5),
        ]
        alerts = scanner.detect_structuring(
            transactions=transactions,
            threshold=Decimal("10000"),
            min_count=3,
            lower_bound_ratio=0.8,
        )
        assert len(alerts) == 0

    def test_no_structuring_when_amounts_too_low(self, scanner):
        transactions = [
            _tx(amount=Decimal("100"), hours_ago=1),
            _tx(amount=Decimal("200"), hours_ago=5),
            _tx(amount=Decimal("150"), hours_ago=10),
        ]
        alerts = scanner.detect_structuring(
            transactions=transactions,
            threshold=Decimal("10000"),
            min_count=3,
            lower_bound_ratio=0.8,
        )
        assert len(alerts) == 0

    def test_structuring_details_include_transaction_ids(self, scanner):
        transactions = [
            _tx(amount=Decimal("9500"), hours_ago=1),
            _tx(amount=Decimal("9800"), hours_ago=5),
            _tx(amount=Decimal("9200"), hours_ago=10),
        ]
        alerts = scanner.detect_structuring(
            transactions=transactions,
            threshold=Decimal("10000"),
            min_count=3,
            lower_bound_ratio=0.8,
        )
        assert "transaction_ids" in alerts[0].details


class TestVelocityDetection:
    def test_detects_high_velocity(self, scanner):
        transactions = [_tx(hours_ago=i * 0.5) for i in range(15)]
        alerts = scanner.detect_velocity(
            transactions=transactions,
            window_hours=24,
            threshold_count=10,
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == "rapid_velocity"

    def test_no_velocity_alert_below_threshold(self, scanner):
        transactions = [_tx(hours_ago=i) for i in range(5)]
        alerts = scanner.detect_velocity(
            transactions=transactions,
            window_hours=24,
            threshold_count=10,
        )
        assert len(alerts) == 0


class TestRoundTripDetection:
    def test_detects_round_trip(self, scanner):
        transactions = [
            _tx(amount=Decimal("10000"), direction="outbound", counterparty="Shell Co", hours_ago=10),
            _tx(amount=Decimal("9800"), direction="inbound", counterparty="Shell Co", hours_ago=5),
        ]
        alerts = scanner.detect_round_trip(
            transactions=transactions,
            tolerance_ratio=0.05,
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == "round_trip"

    def test_no_round_trip_when_amounts_differ_significantly(self, scanner):
        transactions = [
            _tx(amount=Decimal("10000"), direction="outbound", counterparty="Shell Co", hours_ago=10),
            _tx(amount=Decimal("5000"), direction="inbound", counterparty="Shell Co", hours_ago=5),
        ]
        alerts = scanner.detect_round_trip(
            transactions=transactions,
            tolerance_ratio=0.05,
        )
        assert len(alerts) == 0

    def test_no_round_trip_when_different_counterparties(self, scanner):
        transactions = [
            _tx(amount=Decimal("10000"), direction="outbound", counterparty="Company A", hours_ago=10),
            _tx(amount=Decimal("10000"), direction="inbound", counterparty="Company B", hours_ago=5),
        ]
        alerts = scanner.detect_round_trip(
            transactions=transactions,
            tolerance_ratio=0.05,
        )
        assert len(alerts) == 0


class TestScanAll:
    def test_scan_runs_all_detectors(self, scanner):
        structuring_txs = [
            _tx(customer_id="c1", amount=Decimal("9500"), hours_ago=1),
            _tx(customer_id="c1", amount=Decimal("9800"), hours_ago=5),
            _tx(customer_id="c1", amount=Decimal("9200"), hours_ago=10),
        ]
        velocity_txs = [_tx(customer_id="c2", hours_ago=i * 0.5) for i in range(15)]

        all_txs = structuring_txs + velocity_txs
        alerts = scanner.scan(transactions=all_txs, tenant_id="tenant-001")
        alert_types = {a.alert_type for a in alerts}
        assert "structuring" in alert_types
        assert "rapid_velocity" in alert_types

    def test_scan_returns_empty_for_clean_transactions(self, scanner):
        txs = [_tx(customer_id="c1", amount=Decimal("500"), hours_ago=i * 24) for i in range(3)]
        alerts = scanner.scan(transactions=txs, tenant_id="tenant-001")
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Tranche 2 batch patterns
# ---------------------------------------------------------------------------


class TestTrustAccountAnomalyDetection:
    def test_detects_non_client_trust_deposits(self, scanner):
        client_list = {"Known Client A", "Known Client B"}
        transactions = [
            _tx(counterparty="Unknown Source 1", hours_ago=1, metadata={"trust_account": True}),
            _tx(counterparty="Unknown Source 2", hours_ago=5, metadata={"trust_account": True}),
            _tx(counterparty="Unknown Source 3", hours_ago=10, metadata={"trust_account": True}),
        ]
        alerts = scanner.detect_trust_account_anomaly(
            transactions=transactions,
            client_list=client_list,
            min_count=3,
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == "non_client_trust_funds"

    def test_no_alert_when_all_clients_known(self, scanner):
        client_list = {"Known Client A", "Acme Corp"}
        transactions = [
            _tx(counterparty="Known Client A", hours_ago=1, metadata={"trust_account": True}),
            _tx(counterparty="Acme Corp", hours_ago=5, metadata={"trust_account": True}),
            _tx(counterparty="Known Client A", hours_ago=10, metadata={"trust_account": True}),
        ]
        alerts = scanner.detect_trust_account_anomaly(
            transactions=transactions,
            client_list=client_list,
            min_count=3,
        )
        assert len(alerts) == 0

    def test_ignores_non_trust_account_transactions(self, scanner):
        client_list: set[str] = set()
        transactions = [
            _tx(counterparty="Unknown 1", hours_ago=1, metadata={"trust_account": False}),
            _tx(counterparty="Unknown 2", hours_ago=5, metadata={}),
            _tx(counterparty="Unknown 3", hours_ago=10),
        ]
        alerts = scanner.detect_trust_account_anomaly(
            transactions=transactions,
            client_list=client_list,
            min_count=3,
        )
        assert len(alerts) == 0


class TestInterEntityLayeringDetection:
    def test_detects_inter_entity_layering(self, scanner):
        transactions = [
            _tx(hours_ago=1, metadata={"entity_chain": ["HoldCo", "SubCo1", "SubCo2"]}),
            _tx(hours_ago=5, metadata={"entity_chain": ["HoldCo", "SubCo1", "SubCo3"]}),
        ]
        alerts = scanner.detect_inter_entity_layering(
            transactions=transactions,
            min_chain_length=3,
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == "inter_entity_layering"

    def test_no_alert_for_short_entity_chains(self, scanner):
        transactions = [
            _tx(hours_ago=1, metadata={"entity_chain": ["CompA", "CompB"]}),
            _tx(hours_ago=5, metadata={"entity_chain": ["CompA"]}),
        ]
        alerts = scanner.detect_inter_entity_layering(
            transactions=transactions,
            min_chain_length=3,
        )
        assert len(alerts) == 0

    def test_no_alert_when_no_entity_chain_metadata(self, scanner):
        transactions = [
            _tx(hours_ago=1, metadata={}),
            _tx(hours_ago=5, metadata={"other_field": "value"}),
        ]
        alerts = scanner.detect_inter_entity_layering(
            transactions=transactions,
            min_chain_length=3,
        )
        assert len(alerts) == 0
