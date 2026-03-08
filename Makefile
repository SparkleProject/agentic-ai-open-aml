# ==============================================================================
# Makefile — Developer convenience commands
# ==============================================================================
# Usage:  make <target>
#   make install     — Set up local dev environment
#   make dev         — Start app with hot-reload
#   make test        — Run tests
#   make lint        — Lint + type check
#   make up          — Start Docker services
# ==============================================================================

.PHONY: help install dev test lint format check up down clean

.DEFAULT_GOAL := help

# --- Help ---
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup ---
install: ## Install dependencies and pre-commit hooks
	python -m pip install --upgrade pip
	pip install -e ".[dev,ai]"
	pre-commit install
	@echo "✅ Installation complete. Run 'make up' to start Docker services."

# --- Development ---
dev: ## Start the app with hot-reload
	uvicorn aml.main:app --reload --host 0.0.0.0 --port 8000

# --- Testing ---
test: ## Run all tests
	pytest

test-unit: ## Run unit tests only
	pytest -m unit

test-cov: ## Run tests with coverage report
	pytest --cov=aml --cov-report=term-missing --cov-report=html

# --- Linting & Formatting ---
lint: ## Run linter and type checker
	ruff check src/ tests/
	mypy src/

format: ## Auto-format code
	ruff check --fix src/ tests/
	ruff format src/ tests/

check: lint test ## Run all checks (lint + test)

# --- Docker ---
up: ## Start infrastructure services
	docker compose up -d
	@echo "⏳ Waiting for services to be healthy..."
	@sleep 5
	@echo "✅ Services ready. Run 'make dev' to start the app."

down: ## Stop infrastructure services
	docker compose down

clean: ## Stop services and remove volumes
	docker compose down -v
	@echo "🧹 Cleaned up Docker volumes."

# --- Database ---
db-migrate: ## Run Alembic migrations
	alembic upgrade head

db-revision: ## Create a new Alembic migration
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"
