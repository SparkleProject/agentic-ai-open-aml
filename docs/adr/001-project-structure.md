# ADR-001: Backend Project Structure & Technology Choices

**Date:** 2026-03-06
**Status:** Accepted
**Decision Makers:** Engineering & Architecture Lead

## Context

We are bootstrapping the backend for an open-source Agentic AI AML platform.
Key constraints:

- Must support multi-tenant deployment (data isolation per client)
- Must integrate with AWS Bedrock for LLM capabilities
- Must be testable locally without AWS credentials
- Must support an open-source community contribution model
- Target market includes ANZ Tranche 2 entities (lawyers, accountants, real estate)

## Decision

### Language & Framework
**Python 3.12+ with FastAPI**

- Richest AI/ML library ecosystem (LangChain, boto3, scikit-learn)
- Async-first (FastAPI + asyncpg) for high concurrency
- Type hints + Pydantic for runtime validation
- Large contributor pool for open-source adoption

### Project Layout
**`src` layout with domain-based packaging**

```
src/aml/
├── api/       # FastAPI routers, request/response schemas
├── core/      # Config, logging, shared utilities
├── db/        # SQLAlchemy models, Alembic migrations, repositories
├── agents/    # Agent definitions, orchestrator, tool registry
└── services/  # External integrations (Bedrock, vector DB, screening)
```

Rationale: `src` layout prevents accidental imports from working directory
and cleanly separates installed package from project root.

### Database
**PostgreSQL 16 with SQLAlchemy (async) + Alembic**

- Row-Level Security (RLS) for multi-tenant data isolation
- JSONB for flexible schema evolution (agent configs, typologies)
- Alembic for version-controlled schema migrations

### LLM Provider Abstraction
**`ModelProvider` interface with Bedrock, Ollama, and Mock implementations**

- Local development: Ollama or Mock (no AWS credentials needed)
- Staging/Production: AWS Bedrock
- Enables model-agnostic agent development

### Vector Database
**Milvus (self-hosted)**

- Open-source alignment (vs. proprietary Pinecone)
- Namespace isolation per tenant
- Can be replaced via interface abstraction

### Tooling
- **Ruff**: Linting + formatting (replaces Black, isort, flake8)
- **Mypy**: Static type checking (strict mode)
- **Pre-commit**: Automated checks before every commit
- **Pytest**: Testing with async support

## Consequences

- Python's GIL limits CPU-bound parallelism — mitigated by async I/O and
  offloading heavy computation to background workers
- Milvus has a heavier local footprint than Pinecone — mitigated by
  Docker Compose with health checks
- Strict mypy may slow initial development — but prevents bugs at scale

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Java/Spring Boot | Slower iteration cycle, smaller AI ecosystem |
| Go | Excellent performance but weak AI/ML library support |
| Pinecone (vector DB) | Proprietary, conflicts with open-source positioning |
| Django | Sync-first, heavier ORM, less suited for API-only backend |
