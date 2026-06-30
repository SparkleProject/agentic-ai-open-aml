"""Tests for Phase 6 ecosystem integrations (BE-601 to BE-604)."""

from aml.services.events.bus import EventBus, EventType, PlatformEvent
from aml.services.integrations.connectors.xero import XeroIntegration
from aml.services.integrations.protocol import CRMCustomer
from aml.services.regulatory.jurisdiction import JurisdictionRegistry
from aml.services.typology.library import Typology, TypologyLibrary


class TestCRMIntegration:
    async def test_xero_pull_customers(self):
        xero = XeroIntegration()
        customers = await xero.pull_customers("tenant-001")
        assert len(customers) >= 1
        assert isinstance(customers[0], CRMCustomer)
        assert customers[0].external_id.startswith("XERO")

    async def test_xero_push_risk_score(self):
        xero = XeroIntegration()
        result = await xero.push_risk_score("t1", "XERO-001", 75, ["high_risk"])
        assert result is True

    def test_provider_name(self):
        xero = XeroIntegration()
        assert xero.provider_name == "xero"


class TestJurisdictionRegistry:
    def test_get_au_config(self):
        reg = JurisdictionRegistry()
        config = reg.get_config("AU")
        assert config is not None
        assert config.regulator == "AUSTRAC"
        assert "AUSTRAC_SMR" in config.report_types

    def test_get_nz_config(self):
        reg = JurisdictionRegistry()
        config = reg.get_config("NZ")
        assert config is not None
        assert config.currency == "NZD"

    def test_get_us_config(self):
        reg = JurisdictionRegistry()
        config = reg.get_config("US")
        assert config is not None
        assert config.regulator == "FinCEN"

    def test_list_supported(self):
        reg = JurisdictionRegistry()
        supported = reg.list_supported()
        assert "AU" in supported
        assert "NZ" in supported
        assert "US" in supported
        assert "GB" in supported

    def test_get_report_types(self):
        reg = JurisdictionRegistry()
        types = reg.get_report_types("AU")
        assert "AUSTRAC_SMR" in types

    def test_unknown_jurisdiction(self):
        reg = JurisdictionRegistry()
        assert reg.get_config("XX") is None
        assert reg.get_report_types("XX") == []


class TestEventBus:
    async def test_emit_and_subscribe(self):
        bus = EventBus()
        received: list[PlatformEvent] = []

        async def handler(event: PlatformEvent) -> None:
            received.append(event)

        bus.subscribe(EventType.ALERT_CREATED, handler)
        await bus.emit(PlatformEvent(event_type=EventType.ALERT_CREATED, tenant_id="t1"))

        assert len(received) == 1
        assert received[0].tenant_id == "t1"

    async def test_event_log_persisted(self):
        bus = EventBus()
        await bus.emit(PlatformEvent(event_type=EventType.CASE_CLOSED, tenant_id="t1"))
        await bus.emit(PlatformEvent(event_type=EventType.REPORT_SUBMITTED, tenant_id="t1"))

        assert len(bus.event_log) == 2

    async def test_unsubscribed_event_no_handler(self):
        bus = EventBus()
        await bus.emit(PlatformEvent(event_type=EventType.ALERT_RESOLVED))
        assert len(bus.event_log) == 1

    async def test_multiple_handlers(self):
        bus = EventBus()
        count = [0]

        async def h1(event: PlatformEvent) -> None:
            count[0] += 1

        async def h2(event: PlatformEvent) -> None:
            count[0] += 10

        bus.subscribe(EventType.ALERT_CREATED, h1)
        bus.subscribe(EventType.ALERT_CREATED, h2)
        await bus.emit(PlatformEvent(event_type=EventType.ALERT_CREATED))

        assert count[0] == 11


class TestTypologyLibrary:
    def _seed_library(self) -> TypologyLibrary:
        lib = TypologyLibrary()
        lib.add(
            Typology(
                "TYP-001",
                "Cash Structuring",
                "Multiple sub-threshold deposits",
                "structuring",
                "HIGH",
                ["sub-threshold deposits"],
                ["AU", "NZ"],
            )
        )
        lib.add(
            Typology(
                "TYP-002",
                "Trade-Based ML",
                "Over/under-invoicing of goods",
                "trade_based",
                "HIGH",
                ["invoice manipulation"],
                ["AU"],
            )
        )
        lib.add(
            Typology(
                "TYP-003",
                "Crypto Mixing",
                "Use of mixing services",
                "crypto",
                "MEDIUM",
                ["mixing service"],
                ["US", "GB"],
            )
        )
        return lib

    def test_add_and_get(self):
        lib = self._seed_library()
        t = lib.get("TYP-001")
        assert t is not None
        assert t.name == "Cash Structuring"

    def test_search_by_query(self):
        lib = self._seed_library()
        results = lib.search(query="structuring")
        assert len(results) >= 1

    def test_search_by_category(self):
        lib = self._seed_library()
        results = lib.search(category="crypto")
        assert len(results) == 1
        assert results[0].typology_id == "TYP-003"

    def test_search_by_jurisdiction(self):
        lib = self._seed_library()
        results = lib.search(jurisdiction="AU")
        assert len(results) == 2

    def test_adopt_increments_count(self):
        lib = self._seed_library()
        lib.adopt("TYP-001")
        lib.adopt("TYP-001")
        t = lib.get("TYP-001")
        assert t is not None
        assert t.adopted_count == 2

    def test_trending_sorted_by_adoption(self):
        lib = self._seed_library()
        lib.adopt("TYP-002")
        lib.adopt("TYP-002")
        lib.adopt("TYP-002")
        lib.adopt("TYP-001")
        trending = lib.get_trending(limit=2)
        assert trending[0].typology_id == "TYP-002"

    def test_list_all(self):
        lib = self._seed_library()
        assert len(lib.list_all()) == 3
