# High-Level Design (HLD)
**Agentic AI Open AML Platform**

## 1. System Overview
The Agentic AI Open AML platform is an open-source, multi-tenant compliance system tailored for mid-market and Tranche 2 entities (lawyers, accountants, real estate) primarily in the ANZ region.

The system transitions away from legacy rules-based transaction monitoring and introduces an **Agentic AI architecture**, where autonomous LLM-driven agents investigate alerts, reason over financial data, utilize RAG (Retrieval-Augmented Generation) for policy context, and generate regulator-ready Suspicious Activity Reports (SARs/SMRs).

## 2. Architectural Principles
1. **Multi-Tenant by Design**: A single deployment can serve multiple distinct clients (tenants). Data is logically isolated via PostgreSQL Row-Level Security (RLS) and vector database namespaces.
2. **Explainability First (XAI)**: Regulatory compliance requires strict auditability. The system employs an event-sourced "Glass Box" model, meaning every observation, tool invocation, and reasoning step taken by the AI is logged immutably.
3. **Pluggable AI Infrastructure**: LLMs and Embedding models are abstracted. The system integrates securely with AWS Bedrock by default but supports local models (e.g., Ollama) for local development or alternative deployments.
4. **Agentic Orchestration over Pipelines**: The core intelligence uses a state machine (LangGraph) allowing agents to dynamically determine their investigation path rather than following rigid code paths.

## 3. High-Level Architecture Components

### 3.1. Frontend (Client Tier)
- **Tech Stack**: React, TypeScript, Vite/Next.js.
- **Role**: Provides the analyst workspace. Includes the Alert Queue, Case Workspace, XAI Glass Box view, and SAR/SMR editor.
- **Integration**: Communicates with the backend via RESTful JSON APIs and WebSocket connections for real-time agent tracking.

### 3.2. Backend API (Application Tier)
- **Tech Stack**: Python 3.12+, FastAPI, Uvicorn.
- **Role**: Serves as the core integration hub. Handles authentication, authorization (RBAC), tenant context resolution via middleware, and exposes the REST APIs to the frontend.
- **Modules**:
  - `api/`: FastAPI routers and middleware.
  - `db/`: SQLAlchemy ORM and repository patterns.
  - `services/`: External integrations (vector db, authentication).

### 3.3. AI & Agent Orchestration Tier
- **Tech Stack**: LangGraph, LangChain, AWS Bedrock (Claude 3.5 Sonnet / Titan).
- **Role**: The brain of the platform.
- **Modules**:
  - **Orchestrator**: Manages the cyclical `Plan -> Reason -> Act -> Reflect` workflow.
  - **Tool Registry**: Secure execution boundary mapping AI intent to deterministic code (e.g., querying external Sanctions APIs via the Model Context Protocol).
  - **RAG Pipeline**: Ingests and queries compliance typologies and regulatory documents.

### 3.4. Data Storage Tier
- **Relational DB**: PostgreSQL (Async SQLAlchemy). Stores structured entities (`Tenant`, `Customer`, `Transaction`, `Alert`, `Case`). Ensures isolation via RLS.
- **Vector DB**: Milvus (or Pinecone). Stores vector embeddings of regulatory text and local policies for the RAG pipeline. Configured for **Hybrid Search**, combining dense vectors with sparse BM25 indexing for exact-keyword lookups.
- **Audit & Log DB**: Append-only storage (can use Postgres or DynamoDB) for ISO 42001-compliant tracking of all AI reasoning traces.

## 4. End-to-End Execution Flow (Alert to SAR)

1. **Ingestion**: A transaction matches a monitoring rule or anomaly detection, generating an `Alert`.
2. **Triage**: The Alert is queued. The backend triggers the Agent Orchestrator.
3. **Planning**: The `PlannerNode` assesses the alert severity and plots an investigation strategy.
4. **Execution & RAG**: The `ReasonerNode` evaluates the case. It may query the Vector DB for current AUSTRAC typologies or use the Tool Registry to look up the customer's transaction history.
5. **Synthesis**: Once all data is gathered, the agent reaches a conclusion and updates the `Case` status.
6. **Human Review**: The analyst reviews the XAI trail in the Glass Box UI.
7. **Reporting**: If suspicious, the `SARNarrativeAgent` drafts the SMR, the analyst approves, and the system submits it to the regulator via API.
