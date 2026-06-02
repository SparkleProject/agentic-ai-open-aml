from langgraph.graph import END, START, StateGraph  # type: ignore[import-not-found]

from aml.agents.nodes import actor_node, delegator_node, planner_node, reasoner_node, reflector_node
from aml.agents.state import AgentState


def should_continue(state: AgentState) -> str:
    """
    Conditional routing logic based on the reasoner's output.
    """
    observations = state.get("observations", [])
    if not observations:
        return "end"

    latest = observations[-1]
    decision = latest.get("decision")
    if decision == "TOOL":
        return "act"
    if decision == "DELEGATE":
        return "delegate"

    return "end"


def build_orchestrator() -> StateGraph:
    """
    Constructs and returns the LangGraph application for the AML reasoning engine.
    """
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("reasoner", reasoner_node)
    workflow.add_node("actor", actor_node)
    workflow.add_node("delegator", delegator_node)
    workflow.add_node("reflector", reflector_node)

    # Add Edges
    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "reasoner")

    # Conditional logic out of the reasoner
    workflow.add_conditional_edges(
        "reasoner",
        should_continue,
        {"act": "actor", "delegate": "delegator", "end": "reflector"},
    )

    # Actor loops back to reasoner
    workflow.add_edge("actor", "reasoner")

    # Delegator loops back to reasoner
    workflow.add_edge("delegator", "reasoner")

    # Reflector goes to END
    workflow.add_edge("reflector", END)

    return workflow.compile()
