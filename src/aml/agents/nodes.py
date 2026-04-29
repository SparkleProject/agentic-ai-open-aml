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

    return {"plan": plan_text}


async def reasoner_node(state: AgentState) -> dict[str, Any]:
    """
    Evaluates current state against the plan and decides whether to act or conclude.
    Returns JSON.
    """
    plan = state.get("plan", "")
    tools_history = state.get("executed_tools", [])

    tools_str = "\\n".join([f"- {t.tool_name}: {t.result}" for t in tools_history])

    registry = ToolRegistry.get_instance()
    available_schemas = json.dumps(registry.get_tool_schemas(), indent=2)

    prompt = f"""
            Current Plan:
            {plan}

            Executed Tools History:
            {tools_str}

            Decide your next action. You can either:
            1. Request a tool execution
            2. Conclude the investigation

            Output strictly JSON with the format:
            {{
                "decision": "TOOL" | "CONCLUDE",
                "tool_request": {{"name": "ToolName", "parameters": {{...}}}}, // Only if TOOL
                "conclusion": "Final reasoning here" // Only if CONCLUDE
            }}
            """

    system_prompt = (
        "You are an AML reasoning agent. Always output valid JSON.\\n" f"Available tools:\\n{available_schemas}"
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
