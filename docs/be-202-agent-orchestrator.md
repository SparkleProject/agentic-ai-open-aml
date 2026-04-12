# BE-202: Agent Orchestrator (Reasoning Engine) — Architecture & Implementation Plan

**Date:** 2026-04-09
**Status:** DRAFT
**Author:** Engineering & Architecture Lead

## 1. Context & Objective

As defined in the `development-plan.md` Phase 2 roadmap, the **Agent Orchestrator** is the brain of the AML platform. It must possess the ability to run multi-step, autonomous investigations driven by an underlying LLM. The agent must:
- Process an alert context dynamically.
- Plan investigation steps based on risk severity.
- Choose and invoke tools (Sanctions Checks, Transaction History) logically.
- Compile findings into a final explainable rationale.
- Fully support an auditable trail for XAI (Explainable AI) to meet ISO 42001 requirements.

## 2. Architecture Approach: LangGraph State Machine

While the LLM provides reasoning, it requires determinism and reliability around loops, retries, and state persistence.

**Decision:** We will implement the orchestrator using **LangGraph** rather than raw Python loops or legacy LangChain chains.
- **Why LangGraph?** It allows us to explicitly define cyclical node workflows (`Plan -> Observe -> Act -> Reflect`) while preserving the entire operational state natively. Its checkpointer feature inherently solves the problem of "explainability trails" by creating snapshots of every step the agent takes.

## 3. Step-by-Step Implementation Roadmap

### Phase A: Defining State & Context

Before nodes can execute, we must define the payload that passes between them.

1. **Create `src/aml/agents/state.py`**
   - We will define an `AgentState(TypedDict)` (or Pydantic model) containing:
     - `alert_id` & `tenant_id`: Routing and context isolation.
     - `severity`: Determines the exhaustive depth the agent is allowed to plan.
     - `messages`: Standard LLM conversational history.
     - `active_plan`: Text containing unexecuted steps.
     - `executed_tools`: An append-only list of tool results.
     - `conclusion`: The final explainable output (JSON structured).

### Phase B: Upgrading the LLM Abstraction

Currently, `src/aml/services/llm/protocol.py` only defines `generate_response(...) -> str`.

1. **Add Tool-Use Capabilities**
   - Add `invoke_with_tools(..., tools: list[dict]) -> AgentMessage`.
   - The LLM protocol must support returning either text or a dedicated Tool Request (e.g. `tool_name="SearchAdverseMedia", parameters={"company": "Acme Corp"}`).

### Phase C: Implementing ReAct Nodes

1. **Create `src/aml/agents/nodes.py`**
   - **`planner_node`:** Invoked first. It evaluates the Alert and generates a multi-step markdown checklist based on severity.
   - **`reasoner_node`:** Prompts the LLM with the latest state and current plan. The LLM decides whether to request a Tool, or if it has enough info to respond with a final answer.
   - **`actor_node`:** Dynamically invokes functions registered in `src/aml/agents/tools.py`. Catches errors and returns the output to state.
   - **`reflector_node`:** Evaluates the final outcome against the original goal. Ensures regulatory requirements are met before closing the investigation.

### Phase D: Compiling the Graph Orchestrator

1. **Create `src/aml/agents/orchestrator.py`**
   - Initialize `builder = StateGraph(AgentState)`.
   - Add nodes: `builder.add_node("planner", planner_node)`.
   - Wire edges:
     - `START -> planner`
     - `planner -> reasoner`
     - `reasoner -> conditional_edge (tool -> actor | finished -> reflector)`
     - `actor -> reasoner`
     - `reflector -> END`
   - Compile into an executable `app`.

### Phase E: Explainability (XAI) & Cost Tracking

1. **Telemetry & Audit Hooks**
   - LangGraph natively streams events (`app.stream()`). We will iterate over these events and dump the metadata into our database for the XAI Dashboard (task `FE-201`).
   - The orchestrator will load the LLM via `services/llm/factory` wrapped with the `@track_tokens` telemetry (task `BE-103`).

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Infinite Agent Loops** | High (Cost / Timeout) | Use LangGraph `recursion_limit` (e.g., max 10 steps). Enforce a hard fail if LLM repeats same tool identical calls. |
| **Model Incompatibility** | Medium | The `protocol.py` abstraction protects us. If a smaller/local model (Ollama) struggles with tool schemas, we will inject a ReAct parser middleware string prompting scheme instead. |
| **Context Window Bleed** | Medium | Truncate previous, less-relevant observations in the `AgentState` before handing them back to the `reasoner_node`. |
