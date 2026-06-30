# Phase 0: Project Bootstrap & Developer Experience

## 1. Objectives
Establish the foundational infrastructure and developer experience to ensure rapid, high-quality development.

## 2. Core Components

### 2.1 Repository Architecture (P0-01)
- **Monorepo Scaffold**: Organized into `/frontend` and `/backend` packages.
- **Backend Layout**: Domain-driven directory structure (`src/aml/api`, `src/aml/core`, `src/aml/agents`, `src/aml/db`). This ensures separation of concerns between web delivery, core logic, and database access.

### 2.2 Local Developer Environment (P0-03)
- **Docker Compose**: Single-command startup for all dependencies (Postgres, Milvus, Redis) without requiring cloud accounts.
- **Mock Interfaces**: Local development relies on mock model providers or Ollama, ensuring that developers do not need AWS Bedrock credentials to build and test agents locally.

### 2.3 CI/CD & Automation (P0-02)
- **GitHub Actions**: Automated pipelines for testing, linting, and type checking.
- **Code Quality**:
  - `Ruff`: Ultra-fast linting and code formatting.
  - `Mypy`: Strict static type checking to prevent runtime errors in complex agent state manipulations.
  - `Pytest`: Automated test runner with async support for database and API testing.

### 2.4 Documentation & Open Source Guidelines (P0-04, P0-05)
- **Architecture Decision Records (ADR)**: A formalized process for documenting major technical choices (e.g., choosing FastAPI over Django, or LangGraph over raw LangChain).
- **Development Guide**: Standardized PR templates and issue tracking for internal development.
