"""Tests for entity unwrapping resolver and risk annotator (BE-304)."""

import json

from fastapi.testclient import TestClient

from aml.agents.specialized.base import AgentRegistry
from aml.agents.tools.local.entity_unwrap import EntityUnwrapTool
from aml.services.entity.models import CorporateEntity, OwnershipGraph
from aml.services.entity.registry.mock import MockRegistryAdapter
from aml.services.entity.resolver import OwnershipResolver
from aml.services.entity.risk_annotator import EntityRiskAnnotator


class TestOwnershipResolver:
    async def test_simple_chain_identifies_ubo(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-001")

        assert "ACN-001" in graph.entities
        assert "ACN-002" in graph.entities
        assert len(graph.ubos) >= 1
        ubo_names = {u.name for u in graph.ubos}
        assert "Alice Williams" in ubo_names or "Jane Doe" in ubo_names

    async def test_effective_ownership_calculation(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-001")

        alice_ubos = [u for u in graph.ubos if u.name == "Alice Williams"]
        if alice_ubos:
            assert alice_ubos[0].effective_ownership == 60.0

    async def test_circular_ownership_detected(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-CIRCULAR-A")

        flagged = [e for e in graph.entities.values() if "circular_ownership" in e.risk_flags]
        assert len(flagged) >= 1

    async def test_max_depth_respected(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-001", max_depth=0)

        assert len(graph.entities) <= 1

    async def test_unknown_entity_returns_empty(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("NONEXISTENT")

        assert len(graph.entities) == 0
        assert len(graph.ubos) == 0

    async def test_edges_created(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-001")

        assert len(graph.edges) >= 1
        edge_targets = {e.target_id for e in graph.edges}
        assert "ACN-002" in edge_targets

    async def test_injectable_registry(self):
        class EmptyRegistry(MockRegistryAdapter):
            async def lookup(self, entity_id):
                return None

        resolver = OwnershipResolver(registry=EmptyRegistry())
        graph = await resolver.resolve("ACN-001")
        assert len(graph.entities) == 0


class TestEntityRiskAnnotator:
    async def test_annotates_high_risk_jurisdiction(self):
        entity = CorporateEntity(
            entity_id="E1",
            name="Shell Co",
            entity_type="company",
            jurisdiction="IR",
        )
        graph = OwnershipGraph(
            root_entity_id="E1",
            entities={"E1": entity},
        )

        annotator = EntityRiskAnnotator()
        result = annotator.annotate(graph)

        assert "high_risk_jurisdiction" in result.entities["E1"].risk_flags

    async def test_risk_summary_populated(self):
        resolver = OwnershipResolver()
        graph = await resolver.resolve("ACN-001")

        annotator = EntityRiskAnnotator()
        result = annotator.annotate(graph)

        assert "total_entities" in result.risk_summary
        assert "ubo_count" in result.risk_summary


class TestEntityUnwrapTool:
    def test_tool_name(self):
        tool = EntityUnwrapTool()
        assert tool.name == "EntityUnwrapTool"

    async def test_execute_returns_graph_json(self):
        tool = EntityUnwrapTool()
        result = await tool.execute({"entity_id": "ACN-001"})
        parsed = json.loads(result)
        assert "entities" in parsed
        assert "ubos" in parsed
        assert "risk_summary" in parsed

    def test_cdd_agent_has_tool(self):
        agent = AgentRegistry.get_agent("CDDAgent")
        assert "EntityUnwrapTool" in agent.tool_whitelist


class TestEntitiesAPI:
    def test_get_ownership(self, client: TestClient):
        resp = client.get("/api/v1/entities/ACN-001/ownership")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "ubos" in data
        assert "risk_summary" in data

    def test_get_ubos(self, client: TestClient):
        resp = client.get("/api/v1/entities/ACN-001/ubos")
        assert resp.status_code == 200
        data = resp.json()
        assert "ubos" in data
        assert data["count"] >= 1

    def test_search_entities(self, client: TestClient):
        resp = client.get("/api/v1/entities/search?name=HoldCo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_search_no_results(self, client: TestClient):
        resp = client.get("/api/v1/entities/search?name=NonexistentCorp")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
