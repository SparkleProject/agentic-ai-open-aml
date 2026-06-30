# Agentic AI AML Platform

> Proprietary Agentic AI platform for Anti-Money Laundering compliance.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-426%20passing-brightgreen.svg)]()

## What is this?

An AI-powered AML compliance platform that deploys **autonomous agents** to investigate alerts, screen entities, and draft regulatory reports — reducing false positives by up to 90% and investigation times from 45 minutes to under 5.

Built for the **mid-market and Tranche 2** demographic: fintechs, lawyers, accountants, and real estate firms that need affordable, explainable compliance tooling.

### Key Capabilities

| Category | Features |
|---|---|
| **Agentic Core** | LangGraph orchestrator, specialised agents (Sanctions, CDD, Transaction Monitor, SAR Narrative), multi-agent delegation |
| **RAG Pipeline** | Hybrid search (dense + BM25 sparse vectors), Milvus vector store, tenant-isolated knowledge bases |
| **Transaction Monitoring** | Real-time rule engine (7 operators, metadata dot-path access), statistical anomaly scorer, batch pattern detection (structuring, velocity, round-trip) |
| **Regulatory Reporting** | Template-driven SAR/SMR narrative generation, Chain of Verification, AUSTRAC/NZ FIU XML submission adapters |
| **KYC/CDD Automation** | Multi-step onboarding pipeline, pluggable ID verification adapters, weighted risk scoring, 70% automation target |
| **Entity Unwrapping** | Recursive UBO resolution, circular ownership detection, corporate structure graph with risk annotation |
| **Security & Governance** | 3-layer AI guardrails (input/output/PII), SHA-256 hash-chained governance audit trail, ISO 42001 compliance |
| **Authentication** | Pluggable auth provider (Strategy pattern) — built-in JWT, configurable for Cognito/Keycloak |
| **RBAC** | 24 fine-grained permissions, 4 roles (admin, compliance_officer, analyst, auditor), tenant-level customisation |
| **Observability** | Metrics collector, LLM-as-a-Judge evaluation pipeline, A/B testing framework, golden dataset curation |
| **Ecosystem** | CRM integrations (Xero), multi-jurisdiction regulatory adapters (AU/NZ/US/UK), event bus, typology sharing |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                       │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│  Alerts  │  Agents  │ Reports  │   KYC    │  Rules   │  Auth    │
│  Router  │  Router  │  Router  │  Router  │  Router  │  Router  │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│                      Service Layer                               │
│  Monitoring │ Reporting │ KYC │ Entity │ Guardrails │ Governance │
├──────────────────────────────────────────────────────────────────┤
│                    Agent Orchestrator (LangGraph)                 │
│  Planner → Reasoner → Actor → Delegator → Reflector             │
├──────────────────────────────────────────────────────────────────┤
│              Tool Registry + Specialised Agents                  │
│  SanctionsTool │ PEPTool │ TransactionTool │ AdverseMediaTool   │
├──────────────────────────────────────────────────────────────────┤
│                    Data Layer                                     │
│  PostgreSQL (RLS) │ Milvus (RAG) │ Redis (Queue/Cache)          │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for Postgres, Redis, Milvus)

### Setup

```bash
# Clone and install
git clone https://github.com/SparkleProject/agentic-ai-open-aml.git
cd agentic-ai-open-aml
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env

# Start infrastructure
docker compose up -d

# Run the application
uvicorn aml.main:app --reload
```

API: `http://localhost:8000` | Swagger docs: `http://localhost:8000/docs`

### Default credentials (dev only)

After seeding, login with:
- **Email:** `admin@aml.local`
- **Password:** `admin`
- **Tenant:** `default`

### Run tests

```bash
python -m pytest tests/
# 426 passed, 3 skipped
```

## Project Structure

```
src/aml/
├── api/
│   └── routers/          # 11 API routers (alerts, agents, auth, entities,
│                         #   governance, kyc, rag, reports, rules, transactions)
├── agents/
│   ├── orchestrator.py   # LangGraph state machine
│   ├── nodes.py          # Planner, Reasoner, Actor, Delegator, Reflector
│   ├── specialized/      # Agent definitions (Sanctions, CDD, SAR, etc.)
│   └── tools/            # Tool registry + local/MCP tools
├── db/
│   └── models/           # 10 ORM models (User, Tenant, Customer, Transaction,
│                         #   Alert, Case, Report, CDDRecord, GovernanceLog, etc.)
├── services/
│   ├── auth/             # Pluggable auth (JWT provider, factory, permissions)
│   ├── monitoring/       # Rule engine, anomaly scorer, batch scanner, evaluator
│   ├── reporting/        # Narrative generation, verification, submission adapters
│   ├── kyc/              # CDD pipeline, risk scoring, ID verification adapters
│   ├── entity/           # Ownership resolver, risk annotator, registry adapters
│   ├── guardrails/       # Input validator, output validator, PII redactor
│   ├── governance/       # Hash-chained audit logger, chain verifier
│   ├── evaluation/       # LLM-as-Judge, golden dataset, A/B experiments
│   ├── rag/              # Hybrid search RAG service
│   └── ...               # privacy, model_registry, events, integrations, etc.
├── observability/        # Metrics collector, span tracking
└── core/                 # Config, logging, context
```

## API Endpoints

| Prefix | Router | Key Endpoints |
|---|---|---|
| `/api/v1/auth` | Authentication | `POST /login`, `POST /register`, `GET /me`, `GET /users` |
| `/api/v1/alerts` | Alerts | `GET /`, `GET /{id}` |
| `/api/v1/agents` | Investigation | `POST /alerts/{id}/investigate` |
| `/api/v1/transactions` | Ingestion | `POST /`, `POST /batch` |
| `/api/v1/rules` | Rule Management | CRUD + `/dry-run`, `/templates`, `/adopt-pack` |
| `/api/v1/kyc` | KYC/CDD | `POST /onboard`, `GET /customers`, `GET /customers/{id}` |
| `/api/v1/entities` | Entity Unwrapping | `GET /{id}/ownership`, `GET /{id}/ubos`, `GET /search` |
| `/api/v1/reports` | Regulatory Reports | `POST /draft`, `PUT /{id}`, `POST /{id}/submit` |
| `/api/v1/governance` | Audit Trail | `GET /logs`, `POST /verify` |

## Configuration

All settings via environment variables (prefix `AML_`):

| Variable | Default | Description |
|---|---|---|
| `AML_AUTH_PROVIDER` | `jwt` | Auth provider: `jwt`, `cognito`, `keycloak` |
| `AML_JWT_SECRET_KEY` | dev default | JWT signing secret (change in production!) |
| `AML_LLM_PROVIDER` | `mock` | LLM: `mock`, `azure`, `bedrock`, `ollama` |
| `AML_DATABASE_URL` | local postgres | Async SQLAlchemy connection string |
| `AML_REDIS_URL` | `redis://localhost:6379` | Redis for queue/cache |
| `AML_GUARDRAILS_ENABLED` | `false` | Enable input/output/PII guardrails |

## Frontend

The companion frontend is at [agentic-ai-open-aml-ui](https://github.com/SparkleProject/agentic-ai-open-aml-ui).

## Development Phases

| Phase | Status | Components |
|---|---|---|
| Phase 0: Bootstrap | Done | Repo structure, CI/CD, local dev |
| Phase 1: Foundation | Done | Multi-tenant DB, auth, LLM abstraction |
| Phase 2: Agentic Core | Done | Orchestrator, RAG, tools, agents, triage, monitoring |
| Phase 3: Regulatory | Done | SAR/SMR narrative, KYC/CDD, entity unwrapping, rule engine, submission |
| Phase 4: Security | Done | Guardrails, governance logging, privacy, RBAC, model registry |
| Phase 5: Observability | Done | LLM-as-Judge, metrics, A/B testing, golden dataset |
| Phase 6: Ecosystem | Done | CRM integrations, multi-jurisdiction, events, typologies |

See [docs/development-plan.md](docs/development-plan.md) for the full roadmap.

## License

Proprietary. All rights reserved. This software is confidential and not for redistribution.
