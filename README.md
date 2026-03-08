# Agentic AI Open AML

> Open-source Agentic AI platform for Anti-Money Laundering compliance.

[![CI](https://github.com/your-org/agentic-ai-open-aml/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/agentic-ai-open-aml/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](https://opensource.org/licenses/Apache-2.0)

## What is this?

An AI-powered AML compliance platform that deploys **autonomous agents** to investigate alerts, screen entities, and draft regulatory reports — reducing false positives by up to 90% and investigation times from 45 minutes to under 5.

Built for the underserved **mid-market and Tranche 2** demographic: fintechs, lawyers, accountants, and real estate firms that need affordable, explainable compliance tooling.

### Key Capabilities

- 🤖 **Agentic Investigation** — Autonomous multi-step alert investigation with tool use
- 🔍 **RAG-Powered Context** — Retrieval-Augmented Generation over regulatory docs and policies
- 📊 **Explainable AI** — Full reasoning chain visible for every decision
- 📝 **SAR/SMR Drafting** — AI-generated regulator-ready narratives
- 🏢 **Multi-Tenant** — Data-isolated per client with per-tenant cost tracking
- 🌏 **ANZ-First** — AUSTRAC and NZ FIU reporting baked in

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- Make (optional, but recommended)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-org/agentic-ai-open-aml.git
cd agentic-ai-open-aml

# 2. Copy environment config
cp .env.example .env

# 3. Start infrastructure (Postgres, Redis, Milvus)
make up

# 4. Install Python dependencies
make install

# 5. Start the application (hot-reload)
make dev
```

The API will be available at `http://localhost:8000`.
Swagger docs at `http://localhost:8000/docs` (development mode only).

### Verify it works

```bash
curl http://localhost:8000/api/health
# {"status": "ok"}
```

### Run tests

```bash
make test
```

## Project Structure

```
agentic-ai-open-aml/
├── src/aml/              # Application source code
│   ├── api/              #   FastAPI routers & schemas
│   ├── core/             #   Config, logging, utilities
│   ├── db/               #   Database models & migrations
│   ├── agents/           #   AI agent definitions & orchestrator
│   └── services/         #   External integrations (Bedrock, etc.)
├── tests/                # Test suite
├── docs/                 # Documentation & ADRs
│   └── adr/              #   Architecture Decision Records
├── docker-compose.yml    # Local dev infrastructure
├── Dockerfile            # Production container
├── Makefile              # Developer convenience commands
└── pyproject.toml        # Dependencies & tool config
```

## Development

| Command | Description |
|---|---|
| `make install` | Install dependencies + pre-commit hooks |
| `make dev` | Start app with hot-reload |
| `make test` | Run tests |
| `make lint` | Lint + type check |
| `make format` | Auto-format code |
| `make up` | Start Docker services |
| `make down` | Stop Docker services |

See [ADR-001](docs/adr/001-project-structure.md) for architecture decisions.

## Roadmap

See [development-plan.md](development-plan.md) for the full phased roadmap.

## Contributing

We welcome contributions! Please read our contribution guide (coming soon) before submitting PRs.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
