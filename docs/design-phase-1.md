# Phase 1: Multi-Tenant Foundation & Secure AI Infrastructure

## 1. Objectives
Establish the secure, multi-tenant bedrock of the platform. Before any complex AI agents can be deployed, we must ensure strict data isolation between tenants, establish cost-tracking for LLM operations, and build the core entity schemas.

## 2. Core Components

### 2.1 Multi-Tenant Data Layer (BE-102)
- **Database Architecture**: Shared database, isolated schemas or shared schema with Row-Level Security (RLS). We have chosen the **Bridge Pattern** (shared schema + RLS).
- **Implementation**:
  - Every table (except `Tenant`) includes a `tenant_id` column.
  - FastAPI middleware intercepts incoming requests, extracts the `X-Tenant-ID` (or JWT claim), and injects it into a `contextvars` context.
  - The SQLAlchemy async session reads this context and appends `tenant_id` filtering to all queries automatically, preventing cross-tenant data spillage.

### 2.2 Core Data Models (BE-105)
- Foundational domain entities:
  - `Tenant`: Top-level organizational unit.
  - `Customer`: End-users being monitored.
  - `Transaction`: Financial movements.
  - `Alert`: System-generated warnings of suspicious activity.
  - `Case`: Container for an investigation, linking multiple alerts, customers, and evidence.

### 2.3 LLM & Embedding Abstraction Layer (BE-101)
- **Provider Protocol**: The system must not be hardcoded to a single LLM vendor. We define strict Python `Protocols` for `LLMService` and `EmbeddingService`.
- **Implementations**:
  - AWS Bedrock (Claude / Titan) for production.
  - Ollama for local development.
  - Mock for unit testing.
- **Factory**: A factory dynamically instantiates the correct client based on `.env` settings.

### 2.4 Token Usage & Cost Tracking (BE-103)
- Because LLM calls are expensive, multi-tenant systems require strict cost attribution.
- A `@track_tokens` decorator or middleware on the LLM service wraps every invocation.
- It parses usage metadata (input tokens, output tokens) and writes to a telemetry table, linking the cost to the active `tenant_id` and the specific user or agent session.

### 2.5 Authentication & Authorization (BE-104)
- Integrates with an identity provider (IdP) such as AWS Cognito or Keycloak.
- Validates JWT tokens on every request.
- Implements Role-Based Access Control (RBAC) ensuring that only Compliance Officers can approve SARs, while Analysts can only investigate.
