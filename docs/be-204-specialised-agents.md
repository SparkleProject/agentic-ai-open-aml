# BE-204: Specialised Agent Definitions — Architecture & Implementation Plan

**Date:** 2026-05-27
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

As the platform transitions to production, running a single monolithic agent leads to context bloat, increased hallucinations, and high token costs. `BE-204` introduces **Specialised Agent Definitions** where we divide compliance responsibilities among narrow-focus agents:
1. **`SanctionsAgent`:** Focuses on PEP screening and sanctions list matches.
2. **`TransactionMonitorAgent`:** Focuses on financial ledger analysis, wire patterns, and deposit structuring.
3. **`CDDAgent`:** Focuses on Customer Due Diligence, entity resolution, and unwrapping beneficial ownership structures.
4. **`SARNarrativeAgent`:** Focuses strictly on synthesizing investigation history into structured Suspicious Activity/Matter Reports.

Additionally, to handle complex cases, these agents must support **delegation** (collaborating by passing the investigation context to another agent who has the appropriate tools).

---

## 2. Technical Approach: Dynamic Agent State & Delegation

We will enhance the existing LangGraph orchestrator to support specialized contexts without rewriting the state graph structure.

### 2.1 Agent Definition Schema
We define a specialized agent via a class or configuration dataclass:
```python
class AgentDefinition(BaseModel):
    name: str
    description: str
    system_prompt: str
    tool_whitelist: list[str]  # Only subset of tools allowed
    risk_threshold: float
```

### 2.2 Agent Registry
A registry containing the definitions for all available specialized agents.

### 2.3 Agent State & Node Evolution
1. **`AgentState` updates:**
   * `active_agent`: The string identifier of the agent currently executing.
   * `agent_history`: A list tracking delegation paths (e.g. `["SanctionsAgent", "CDDAgent"]`).
2. **`reasoner_node` updates:**
   * Reads `state["active_agent"]` to look up the active agent's `system_prompt` and `tool_whitelist`.
   * Formats the available tools list exposed to the LLM to *only* include the tools in the whitelist.
   * Updates the reasoning prompt to allow a third decision type: `DELEGATE`.
3. **Delegation routing:**
   * If the LLM returns `{"decision": "DELEGATE", "delegate_to": "CDDAgent", "reason": "..."}`, the active agent is updated, and the graph loops back to the reasoner under the new agent's context.

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Create Specialized Agent Models and Configurations
* **File:** `src/aml/agents/specialized/base.py` and definitions.
* Define `AgentDefinition` and concrete agent profiles:
  * `SanctionsAgent`: whitelist `["SanctionsScreeningTool", "PEPScreeningTool"]`.
  * `TransactionMonitorAgent`: whitelist `["TransactionLookupTool"]`.
  * `CDDAgent`: whitelist `["TransactionLookupTool"]` (future: ASIC lookup).
  * `SARNarrativeAgent`: whitelist `[]` (no tools, purely synthesis).

### Step 2: Update Agent State
* **File:** `src/aml/agents/state.py`
* Add fields:
  * `active_agent: str`
  * `agent_history: list[str]` (using `operator.add` or standard list concat)

### Step 3: Enhance `reasoner_node` and Graph Edges
* **File:** `src/aml/agents/nodes.py` & `src/aml/agents/orchestrator.py`
* In `reasoner_node`:
  * Load active agent from `state["active_agent"]` (default to a general agent or `SanctionsAgent` if not set).
  * Filter tools returned by `registry.get_tool_schemas()` based on the agent's whitelist.
  * Append the agent's unique `system_prompt` to the LLM system message.
  * Adjust JSON schema validation to support:
    ```json
    {
        "decision": "TOOL" | "CONCLUDE" | "DELEGATE",
        "tool_request": { ... },
        "delegate_request": { "name": "AgentName", "reason": "..." },
        "conclusion": "..."
    }
    ```
* In `orchestrator.py`:
  * Update conditional edge `should_continue` to handle `DELEGATE` transition, routing back to `reasoner` after updating `active_agent` and appending to `agent_history`.

### Step 4: Update the Investigate API Router
* **File:** `src/aml/api/routers/agents.py`
* Initialize `active_agent` inside `initial_state` dynamically based on the alert type (e.g. `sanctions_match` starts with `SanctionsAgent`, `structuring_patterns` starts with `TransactionMonitorAgent`).

### Step 5: Extend Tests & Mocks
* **File:** `src/aml/services/llm/mock.py` and `tests/test_agent_orchestrator.py`
* Update mock responses to simulate delegation (e.g. `SanctionsAgent` delegates to `CDDAgent`, then `CDDAgent` concludes).
* Verify dynamic whitelisting and delegation transitions in `test_agent_orchestrator.py`.
