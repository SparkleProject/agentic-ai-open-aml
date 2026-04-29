# BE-203: Tool Registry & MCP Integration — Architecture Plan

**Date:** 2026-04-12
**Status:** DRAFT
**Author:** Engineering & Architecture Lead

## 1. Context & Objective

As defined in the Phase 2 roadmap, the LangGraph Reasoning Engine from BE-202 is only as capable as the APIs it can access. Currently, `src/aml/agents/nodes.py` uses a hardcoded dictionary (`AVAILABLE_TOOLS`) with dummy responses.

The **BE-203 Tool Registry** will replace this. Following the strategy in `development-plan.md`, we need a robust integration layer accommodating:
1. Native local Python functions.
2. External services utilizing the **Model Context Protocol (MCP)** standard (allowing tools to exist as remote microservices with completely independent rate limits and scaling).

## 2. Architecture Approach: Unified Registry + MCP Proxy

The architecture will unify all tool executions under a `BaseTool` abstraction. We will implement three structural layers inside `src/aml/agents/tools/`:
1. **Core Protocol/Registry:** Manages tool discovery and centralized execution.
2. **Local Tools Layer:** Standard internal Pydantic-validated functions (e.g., direct DB queries for `TransactionLookup`).
3. **MCP Tool Proxy Layer:** A proxy class that queries external HTTP/SSE MCP endpoints, retrieves their JSON schemas, and dynamically maps them into the LangGraph orchestrator.

## 3. Step-by-Step Implementation Roadmap

### Phase A: Define Tool Protocols & Interfaces

1. **Create `src/aml/agents/tools/protocol.py`**
   - Create generic mappings standardizing Anthropic/OpenAI schema styles:
   - `BaseTool(Protocol)` requiring:
     - `name`: Identifies the tool to the LLM.
     - `description`: The critical LLM prompt detailing when/how to use the tool.
     - `schema`: A Pydantic schema enforcing required parameters.
     - `execute(params: dict) -> str`: The invoker function.

### Phase B: Build the Tool Registry Singleton

1. **Create `src/aml/agents/tools/registry.py`**
   - Build a `ToolRegistry` class designed to be instantiated per tenant (or globally with tenant context injection).
   - Methods:
     - `register(tool: BaseTool)`
     - `get_tool_schemas() -> list[dict]`: Dumps out all registered tool schemas directly into the prompt format required by our `reasoner_node`.
     - `execute(tool_name: str, params: dict) -> str`: The central router.

### Phase C: Implement Baseline Local Tools

1. **Create `src/aml/agents/tools/local/screening.py`**
   - `SanctionsTool`: Accepts `{ "entity_name": "...", "dob": "..." }`, simulates checking against OFAC/UN lists.
   - `PEPScreeningTool`: Simulates checking if a person is a Politically Exposed Person.
2. **Create `src/aml/agents/tools/local/transactions.py`**
   - `TransactionLookupTool`: Given a `customer_id`, queries the `transactions` table (mocked via SQLAlchemy bindings later) returning recent activity.

### Phase D: Model Context Protocol (MCP) Foundation

1. **Create `src/aml/agents/tools/mcp/client.py`**
   - *Architecture Note:* Instead of building tools permanently in the monolith, MCP specifies building an interface proxy.
   - `MCPClientTool` implements `BaseTool`. It takes a `server_url`. Upon initialization, it hits the remote server's `/tools` endpoint to gather its properties, and maps `.execute()` to HTTP POSTs against the external service.

### Phase E: Integrate with BE-202 LangGraph

1. **Update `src/aml/agents/nodes.py`**
   - Remove the `AVAILABLE_TOOLS` static dict.
   - Refactor the `actor_node` to instantiate the `ToolRegistry` and invoke `registry.execute(...)`.
   - Refactor the `reasoner_node` prompt formatting to dynamically load the LLM's system prompt containing schemas from `registry.get_tool_schemas()`. This guarantees the LLM only attempts to use tools registered to the specific tenant's subscription.

## 4. Resilience & Error Handling

When reaching out to external MCP services or internal databases, things will fail (Rate limits, timeouts).
- **Graceful Observation Failure:** If `registry.execute()` encounters a Python Exception or HTTP Error, it MUST NOT crash the orchestrator.
- Instead, it will catch the error and return `{"error": "External service timed out. Suggest retrying or skipping."}`. The `System` returns this string as the result of the Tool turn, allowing the LLM `reasoner_node` to organically *observe* the failure and make a secondary plan.
