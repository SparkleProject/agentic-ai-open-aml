"""
Definitions and profiles for specialized compliance agents.
Supports whitelisted tools and custom system prompts per role.
"""

from typing import ClassVar

from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    name: str = Field(description="Name of the specialized agent.")
    description: str = Field(description="Visual or text description of the agent's focus.")
    system_prompt: str = Field(description="Custom guidelines and behavioral constraints.")
    tool_whitelist: list[str] = Field(
        description="Strict subset of whitelisted tool names this agent is allowed to run."
    )
    risk_threshold: float = Field(default=20.0, description="Minimum priority score needed to escalate.")


# Specialized agent profiles
SANCTIONS_AGENT = AgentDefinition(
    name="SanctionsAgent",
    description="Agent dedicated to validating PEP flags and sanctions matches.",
    system_prompt=(
        "You are the SanctionsAgent, a specialized compliance officer focusing strictly on "
        "identity matching, PEP screening, and sanctions validation.\n"
        "Your task is to check if names fuzzy or exactly match global watchlists. Keep your "
        "analysis narrow and do not speculate on transactions.\n"
        "If you need to analyze financial ledgers or deposit structuring, you MUST "
        "DELEGATE to the TransactionMonitorAgent."
    ),
    tool_whitelist=["SanctionsScreeningTool", "PEPScreeningTool"],
)

TRANSACTION_MONITOR_AGENT = AgentDefinition(
    name="TransactionMonitorAgent",
    description="Agent dedicated to transaction anomalies, structuring, and cash deposits.",
    system_prompt=(
        "You are the TransactionMonitorAgent, a specialized compliance officer focused "
        "strictly on bank transfers, wire deposits, and structuring patterns.\n"
        "Verify transactions for irregular flows, high velocity, or round amounts. Do not "
        "speculate on sanction checks.\n"
        "If you need to verify beneficial ownership or ASIC registries, you MUST "
        "DELEGATE to the CDDAgent."
    ),
    tool_whitelist=["TransactionLookupTool"],
)

CDD_AGENT = AgentDefinition(
    name="CDDAgent",
    description="Agent focused on Customer Due Diligence, entity resolution, and corporate unwrapping.",
    system_prompt=(
        "You are the CDDAgent, focused strictly on Customer Due Diligence, KYC status, and "
        "corporate ownership hierarchy (ASIC lookup, UBO unwrapping).\n"
        "Ensure beneficial owners have valid ID checks. If you need transaction history "
        "or sanctions verification, DELEGATE to the appropriate agent."
    ),
    tool_whitelist=["TransactionLookupTool", "AdverseMediaTool", "EntityUnwrapTool"],
)

SAR_NARRATIVE_AGENT = AgentDefinition(
    name="SARNarrativeAgent",
    description="Agent specialized in drafts of SMR/SAR regulator narratives.",
    system_prompt=(
        "You are the SARNarrativeAgent, specialized in synthesizing complete compliance "
        "histories and audit trails into structured, regulator-ready narratives.\n"
        "Use the NarrativeDraftTool to generate a draft report. Specify the case_id and "
        "report_type (e.g. AUSTRAC_SMR, NZ_SAR) to produce a formatted narrative."
    ),
    tool_whitelist=["NarrativeDraftTool"],
)


class AgentRegistry:
    """Master repository containing specialized agent definitions."""

    _agents: ClassVar[dict[str, AgentDefinition]] = {
        "SanctionsAgent": SANCTIONS_AGENT,
        "TransactionMonitorAgent": TRANSACTION_MONITOR_AGENT,
        "CDDAgent": CDD_AGENT,
        "SARNarrativeAgent": SAR_NARRATIVE_AGENT,
    }

    @classmethod
    def get_agent(cls, name: str) -> AgentDefinition:
        """Fetch specialized agent details by name, default to SanctionsAgent on missing."""
        return cls._agents.get(name, SANCTIONS_AGENT)

    @classmethod
    def list_agents(cls) -> list[str]:
        """List all available agent names."""
        return list(cls._agents.keys())
