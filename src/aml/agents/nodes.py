import json
from typing import Any

from aml.agents.state import AgentState, ToolCallResult
from aml.agents.tools.registry import ToolRegistry
from aml.core.config import get_settings
from aml.services.llm.factory import get_llm_provider


async def planner_node(state: AgentState) -> dict[str, Any]:
    """
    Given an alert, generates an exhaustive plan of attack.
    """
    prompt = (
        f"Alert ID: {state.get('alert_id')}\\nSeverity: {state.get('severity')}\\n"
        "Generate a concise text-based multi-step plan to investigate this alert."
    )
    system_prompt = "You are an expert AML investigator. Outline a plan."

    settings = get_settings()
    llm = get_llm_provider(settings)  # Replace with dynamic resolving logic later

    plan_text = await llm.generate_response(prompt=prompt, system_prompt=system_prompt, temperature=0.2)

    active_agent = state.get("active_agent") or "SanctionsAgent"

    return {
        "plan": plan_text,
        "active_agent": active_agent,
        "agent_history": [active_agent] if not state.get("agent_history") else [],
    }


async def reasoner_node(state: AgentState) -> dict[str, Any]:
    """
    Evaluates current state against the plan and decides whether to act, delegate, or conclude.
    Returns JSON.
    """
    plan = state.get("plan", "")
    tools_history = state.get("executed_tools", [])

    tools_str = "\n".join([f"- {t.tool_name}: {t.result}" for t in tools_history])

    from aml.agents.specialized.base import AgentRegistry

    active_agent_name = state.get("active_agent") or "SanctionsAgent"
    agent_def = AgentRegistry.get_agent(active_agent_name)

    registry = ToolRegistry.get_instance()
    all_schemas = registry.get_tool_schemas()

    # Filter schemas down to only those whitelisted by the active agent
    whitelisted_schemas = [s for s in all_schemas if s["name"] in agent_def.tool_whitelist]
    available_schemas = json.dumps(whitelisted_schemas, indent=2)

    prompt = f"""
            Current Plan:
            {plan}

            Executed Tools History:
            {tools_str}

            You are currently executing as the specialized agent: {agent_def.name}.
            Agent Description: {agent_def.description}
            Specialized Guidelines:
            {agent_def.system_prompt}

            Decide your next action. You can either:
            1. Request a tool execution (Must be from your whitelisted available tools below)
            2. Delegate the investigation to a different specialized agent
               (Use this if you need information or actions that require tools outside your whitelist)
            3. Conclude the investigation

            Output strictly JSON with the format:
            {{
                "decision": "TOOL" | "CONCLUDE" | "DELEGATE",
                "tool_request": {{"name": "ToolName", "parameters": {{...}}}}, // Only if TOOL
                "delegate_request": {{"name": "AgentName", "reason": "Why you are delegating"}}, // Only if DELEGATE
                "conclusion": "Final reasoning here" // Only if CONCLUDE
            }}
            """

    system_prompt = (
        f"You are the {agent_def.name}. Always output valid JSON.\n" f"Available tools for you:\n{available_schemas}"
    )

    settings = get_settings()
    llm = get_llm_provider(settings)

    json_response = await llm.generate_response(prompt=prompt, system_prompt=system_prompt, temperature=0.1)

    # Basic JSON parsing
    try:
        # Strip markdown codeblocks if LLM included them
        clean_json = json_response.replace("```json", "").replace("```", "").strip()
        decision_data = json.loads(clean_json)
        return {"observations": [decision_data]}
    except json.JSONDecodeError:
        # Fallback error state
        return {"observations": [{"decision": "CONCLUDE", "conclusion": "Failed to parse reasoning output."}]}


async def actor_node(state: AgentState) -> dict[str, Any]:
    """
    Executes the tool requested by the reasoner.
    """
    observations = state.get("observations", [])
    if not observations:
        return {}

    # Grab the most recent reasoning decision
    latest_decision = observations[-1]

    if latest_decision.get("decision") != "TOOL":
        return {}

    tool_req = latest_decision.get("tool_request", {})
    tool_name = tool_req.get("name")
    tool_params = tool_req.get("parameters", {})

    registry = ToolRegistry.get_instance()
    result = await registry.execute(str(tool_name), tool_params)

    return {"executed_tools": [ToolCallResult(tool_name=str(tool_name), result=result)]}


def reflector_node(state: AgentState) -> dict[str, Any]:
    """
    Finalizes the alert. Synthesizes the decision into ISO-42001 explainable structure.
    """
    observations = state.get("observations", [])
    final_conclusion = "No conclusion found."

    if observations:
        latest = observations[-1]
        if latest.get("decision") == "CONCLUDE":
            final_conclusion = latest.get("conclusion", "")

    # Normally we'd do one more LLM call here to format standard SAR/SMR narrative.

    return {
        "conclusion": {
            "status": "COMPLETED",
            "narrative": final_conclusion,
            "steps_taken": len(state.get("executed_tools", [])),
        }
    }


def delegator_node(state: AgentState) -> dict[str, Any]:
    """
    State-updating node executed on delegation.
    Extracts the delegation request and updates active_agent and agent_history.
    """
    observations = state.get("observations", [])
    if not observations:
        return {}

    latest = observations[-1]
    delegate_req = latest.get("delegate_request", {})
    target_agent = delegate_req.get("name", "CDDAgent")

    return {
        "active_agent": target_agent,
        "agent_history": [target_agent],
    }
