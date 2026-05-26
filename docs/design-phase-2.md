# Phase 2: Agentic Core — Orchestration, RAG & Tools

## 1. Objectives
Build the platform's "brain." Transition from standard LLM prompts to an autonomous agent capable of utilizing external tools, maintaining conversational state, and executing long-running investigations.

## 2. Core Components

### 2.1 Agent Orchestrator (BE-202)
- **Framework**: Built on LangGraph to provide cyclic execution and state management.
- **State Definition**: Uses `AgentState` to track context (messages, current plan, active alert, execution history).
- **Node Execution Loop**:
  1. **Planner**: Evaluates the alert and writes an investigation plan.
  2. **Reasoner**: Decides the immediate next step. Can either supply a final answer or request a tool.
  3. **Actor**: Executes requested tools and updates the state.
  4. **Reflector**: Reviews the output to ensure quality and compliance.

### 2.2 Tool Registry & MCP Integration (BE-203)
- **Tool Abstraction**: Agents cannot run raw Python. They emit structural tool requests. The Tool Registry maps these requests to actual functions.
- **Model Context Protocol (MCP)**: Utilized to proxy requests to external systems securely.
- **Available Tools**:
  - `ScreeningTool`: Checks PEPs and sanctions lists.
  - `TransactionTool`: Pulls 90-day history for a customer.
  - `OSINTTool`: Gathers external media context.

### 2.3 RAG Pipeline & Context Optimiser (BE-201)
- **Vector Storage**: Uses Milvus with tenant-isolated namespaces.
- **Ingestion**: Chunks regulatory documents (e.g., AUSTRAC typologies) and local company policies into embeddings via the Embedding Service.
- **Retrieval**: The orchestrator can query the RAG pipeline dynamically during an investigation. Uses **Hybrid Search (Vector + BM25)** to ensure conceptual matching (e.g., "suspicious patterns") combined with exact keyword matching (e.g., "Section 43B", specific SWIFT codes, or product IDs).

### 2.4 Specialized Agent Definitions (BE-204)
- Rather than one monolithic agent, we utilize specialized sub-agents with narrow focuses to reduce hallucination and context bloat.
- **Examples**:
  - `SanctionsAgent`: Only has access to screening tools and focuses strictly on name-matching logic.
  - `CDDAgent`: Focuses on Customer Due Diligence, entity resolution, and UBO unwrapping.

### 2.5 Alert Triage & Prioritization (BE-205)
- Pre-processing step before human interaction.
- Uses lighter, faster models to auto-score incoming alerts based on the RAG policy context.
- Allows for automated clearing of obvious false positives (saving significant analyst hours).
