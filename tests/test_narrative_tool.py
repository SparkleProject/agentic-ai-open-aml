"""Tests for NarrativeDraftTool agent integration (BE-301 Step 6)."""

import json

from aml.agents.specialized.base import AgentRegistry
from aml.agents.tools.local.reporting import NarrativeDraftTool
from aml.services.llm.mock import MockLLMProvider


class TestNarrativeDraftTool:
    def test_tool_name(self):
        tool = NarrativeDraftTool()
        assert tool.name == "NarrativeDraftTool"

    def test_tool_description(self):
        tool = NarrativeDraftTool()
        assert "narrative" in tool.description.lower()
        assert "report" in tool.description.lower()

    def test_tool_input_schema(self):
        tool = NarrativeDraftTool()
        schema = tool.input_schema
        assert "case_id" in schema["properties"]
        assert "report_type" in schema["properties"]

    async def test_tool_execute_returns_json(self):
        smr_sections = {
            "Subject Details": "John Smith.",
            "Suspicious Activity Description": "Structuring detected.",
            "Transaction Details": "TXN-001: $9,900.",
            "Reporting Entity Information": "AML Corp.",
            "Reason for Suspicion": "AML/CTF Act s.41.",
        }
        MockLLMProvider.canned_responses = [json.dumps(smr_sections)]

        tool = NarrativeDraftTool()
        result = await tool.execute(
            {
                "case_id": "case-123",
                "report_type": "AUSTRAC_SMR",
            }
        )

        parsed = json.loads(result)
        assert "sections" in parsed
        assert parsed["report_type"] == "AUSTRAC_SMR"

    async def test_tool_rejects_missing_params(self):
        tool = NarrativeDraftTool()
        result = await tool.execute({"case_id": "case-123"})
        assert "error" in result.lower()


class TestSARNarrativeAgentIntegration:
    def test_sar_agent_has_narrative_tool(self):
        agent = AgentRegistry.get_agent("SARNarrativeAgent")
        assert "NarrativeDraftTool" in agent.tool_whitelist

    def test_sar_agent_is_registered(self):
        assert "SARNarrativeAgent" in AgentRegistry.list_agents()
