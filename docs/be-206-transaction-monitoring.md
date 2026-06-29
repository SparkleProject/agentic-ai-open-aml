# BE-206: Transaction Monitoring Engine — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Phase 2 components BE-201 through BE-205 deliver the agentic core: orchestrator, RAG, tools, specialised agents, and alert triage. However, the platform currently has no mechanism for *generating* alerts from raw transaction data. Alerts are assumed to exist in the database. BE-206 closes this gap by building the **Transaction Monitoring Engine** — the subsystem that continuously evaluates transactions against deterministic rules and anomaly detection models to produce the alerts that the agentic core investigates.

The engine must support:
1. **Real-time monitoring** — evaluate individual transactions at ingest time against a rule set.
2. **Batch monitoring** — periodically scan historical transaction windows for patterns invisible at the individual level (e.g., structuring over 48 hours).
3. **Event-driven architecture** — decouple transaction ingestion from alert creation using an async queue.
4. **Tenant-scoped rules** — each tenant configures their own thresholds, typologies, and risk appetite.

### Tranche 2 Data Model Considerations

Tranche 2 entities (lawyers, accountants, real estate agents) are **not banks**. They do not have access to banking transaction feeds. Their "transactions" are business records from their own operations:

| Entity Type | Transaction Sources | Examples |
|---|---|---|
| **Real estate agents** | Property settlements, trust account movements, deposit receipts | AgentBox, Rex, PropertyMe |
| **Lawyers** | Trust account deposits/withdrawals, settlement funds, client payments | LEAP, Smokeball, Actionstep |
| **Accountants** | Client payments, invoices, tax refund flows, inter-entity transfers | Xero, MYOB, QuickBooks |
| **Precious metals dealers** | Cash purchases, high-value sales, consignment records | POS systems, manual entry |

Data enters the system via three paths:
1. **CRM/ERP sync (BE-601)** — Xero/MYOB/Salesforce integration pulls invoices, payments, and client records automatically. An Xero invoice payment becomes a `Transaction` record.
2. **Batch upload (this API, `/transactions/batch`)** — CSV or JSON upload of trust account movements, settlement records, etc. for firms using niche practice management software.
3. **Practice management API connectors** — Future extension of BE-601 for industry-specific tools (LEAP, PropertyMe).

The existing `Transaction` model handles this well: `amount`, `currency`, `direction`, `counterparty`, and `metadata_` (JSONB) are generic. The `metadata_` field carries industry-specific context, e.g.:
- Real estate: `{"property_address": "...", "settlement_type": "cash", "purchaser_type": "nominee"}`
- Legal: `{"trust_account": true, "matter_id": "...", "fund_source": "overseas"}`
- Accounting: `{"invoice_id": "...", "entity_chain": ["HoldCo", "SubCo1", "SubCo2"]}`

### Dependencies on Existing Code
- `src/aml/db/models/transaction.py` — The `Transaction` ORM model (amount, currency, direction, counterparty, metadata).
- `src/aml/db/models/alert.py` — The `Alert` ORM model and `AlertSeverity`/`AlertStatus` enums.
- `src/aml/db/models/customer.py` — The `Customer` ORM model with `risk_rating`.
- `src/aml/core/config.py` — `Settings` class (already has `redis_url` for queue backing).
- `src/aml/services/triage/service.py` — Downstream consumer: alerts generated here flow into triage (BE-205) and then the orchestrator (BE-202).

---

## 2. Architecture Approach: Rule Engine + Anomaly Scoring

```
                        ┌──────────────┐
  Transaction Ingest ──>│  Async Queue  │──> Real-time Evaluator ──> Alert Creator
   (API / Batch ETL)    │  (Redis/SQS)  │         │
                        └──────────────┘         │
                                                  ├── Deterministic Rules (YAML)
                                                  └── Anomaly Scorer (statistical)

                        ┌──────────────┐
  Cron / Scheduler ────>│ Batch Scanner │──> Pattern Detector ──> Alert Creator
                        └──────────────┘
```

### 2.1 Deterministic Rule Engine
Configurable YAML-based rules evaluated per-transaction. Each rule specifies conditions (field comparisons, thresholds) and an output (alert type, severity). Rules are tenant-scoped and hot-reloadable.

### 2.2 Anomaly Scorer
Statistical model that evaluates a transaction against the customer's historical profile. Uses z-score or IQR-based deviation to flag outliers without requiring ML training data in Phase 2.

### 2.3 Batch Pattern Detector
Runs on a schedule (e.g., every 15 minutes). Queries transaction windows to detect multi-transaction patterns: structuring (multiple sub-threshold deposits), rapid movement (high velocity), round-tripping, and fan-out/fan-in.

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Rule Schema and Rule Engine Core

**Files:**
- `src/aml/services/monitoring/rules.py`
- `src/aml/services/monitoring/schemas.py`

**Implementation Details:**
- Define a `MonitoringRule` Pydantic model:
  ```python
  class MonitoringRule(BaseModel):
      id: str
      name: str
      description: str
      conditions: list[RuleCondition]  # field, operator, value
      alert_type: str
      severity: AlertSeverity
      enabled: bool = True
  ```
- Define `RuleCondition` supporting operators: `gt`, `gte`, `lt`, `lte`, `eq`, `in`, `contains`.
- Implement `RuleEngine` class with:
  - `load_rules(tenant_id: str) -> list[MonitoringRule]` — loads from YAML files or tenant settings JSON.
  - `evaluate(transaction: Transaction, rules: list[MonitoringRule]) -> list[RuleMatch]` — returns matched rules.
- Ship with a default rule set covering AUSTRAC-relevant patterns:
  - Cash deposits ≥ $10,000 (threshold reporting).
  - Rapid same-day transactions to same counterparty.
  - Transactions to high-risk jurisdictions.

**Why:** Deterministic rules are the compliance baseline. Regulators expect pattern matching on known typologies before any AI-based detection. YAML-based rules allow compliance officers to update thresholds without code changes.

### Step 2: Implement Anomaly Scorer

**Files:**
- `src/aml/services/monitoring/anomaly.py`

**Implementation Details:**
- Implement `AnomalyScorer` class:
  - `score_transaction(transaction: Transaction, profile: CustomerProfile) -> AnomalyResult`
  - `CustomerProfile` is a lightweight data class aggregating a customer's mean transaction amount, standard deviation, typical counterparties, usual currencies, and transaction frequency (computed from the last 90 days).
- Scoring method: compute z-score for amount, frequency deviation, and counterparty novelty. Combine into a composite anomaly score (0-100).
- `AnomalyResult` contains: `score: float`, `factors: list[str]` (human-readable explanations of what triggered the score).

**Why:** Statistical anomaly detection catches novel patterns that no predefined rule covers. Z-score requires no training data — it works from the customer's own transaction history. The `factors` list feeds directly into the alert description for XAI transparency.

### Step 3: Build the Real-Time Transaction Evaluator

**Files:**
- `src/aml/services/monitoring/evaluator.py`

**Implementation Details:**
- Implement `TransactionEvaluator` class:
  - `async evaluate(transaction: Transaction, tenant_id: str) -> list[Alert]`
  - Loads tenant rules via `RuleEngine.load_rules()`.
  - Runs the transaction through both the rule engine and anomaly scorer.
  - For each match/threshold breach, creates an `Alert` record with:
    - `alert_type` from the matched rule or `anomaly_detection`.
    - `severity` from the rule or mapped from the anomaly score.
    - `description` combining rule name + anomaly factors.
    - `details` JSON containing the full match context (rule ID, scores, transaction snapshot).
  - Deduplication: checks if an alert for the same customer + alert_type already exists within a configurable window (default 24 hours) to avoid duplicate alerts.

**Why:** The evaluator is the central orchestration point. It fans out to both detection methods and consolidates results into Alert records that downstream services (triage, orchestrator) consume.

### Step 4: Implement Batch Pattern Scanner

**Files:**
- `src/aml/services/monitoring/batch.py`

**Implementation Details:**
- Implement `BatchPatternScanner` class:
  - `async scan(tenant_id: str, window_hours: int = 48) -> list[Alert]`
  - Queries the `Transaction` table for the time window, grouped by customer.
  - Evaluates configurable multi-transaction patterns:
    - **Structuring detection:** Multiple transactions just under a threshold (e.g., 3+ transactions between $8,000-$9,999 within 48 hours).
    - **Velocity detection:** Transaction count exceeding the customer's historical average by > 3x.
    - **Round-tripping:** Outbound followed by similar inbound from a related counterparty.
    - **Fan-out/fan-in:** Single source distributing to many recipients, or many sources consolidating to one.
  - **Tranche 2-specific batch patterns** (evaluated using `metadata_` fields):
    - **Rapid property flipping:** Same `metadata_.property_address` appears in sell + buy transactions within 180 days.
    - **Inter-entity layering:** Client with 3+ related entities (`metadata_.entity_chain`) moving funds between them within 48 hours.
    - **Trust account anomalies:** Trust account receiving funds from non-client sources across multiple transactions.
  - Each detected pattern generates an Alert with `alert_type` describing the pattern and `details` containing the full transaction set.

**Why:** Many money laundering typologies (especially structuring and layering) are only visible across multiple transactions over time. Real-time evaluation cannot catch these — a periodic batch scan is necessary. The 48-hour default window aligns with AUSTRAC's structuring detection guidelines. The Tranche 2-specific patterns leverage the `metadata_` JSONB field to detect industry-specific risks that banking-focused patterns miss entirely.

### Step 5: Create Transaction Ingestion API and Queue Integration

**Files:**
- `src/aml/api/routers/transactions.py`
- `src/aml/services/monitoring/queue.py`

**Implementation Details:**
- **API Router** (`transactions.py`):
  - `POST /api/v1/transactions` — Accepts a transaction payload, validates via Pydantic, persists to DB, and publishes to the monitoring queue.
  - `POST /api/v1/transactions/batch` — Accepts a list of transactions for bulk ingestion (batch ETL use case).
  - Both endpoints return the created transaction ID(s) and any immediately-generated alerts.
- **Queue Service** (`queue.py`):
  - `MonitoringQueue` class wrapping Redis Streams (using the `redis_url` from `Settings`).
  - `publish(transaction_id: str, tenant_id: str)` — enqueues a transaction for async evaluation.
  - `consume(handler: Callable)` — consumer loop that reads from the stream and calls the `TransactionEvaluator`.
  - Falls back to synchronous evaluation if Redis is unavailable (development mode).

**Why:** Decoupling ingestion from evaluation via a queue prevents transaction write latency from being blocked by rule evaluation. Redis Streams provide ordering guarantees, consumer groups (for horizontal scaling), and built-in acknowledgment. The sync fallback ensures the platform works without Redis in local development.

### Step 6: Wire into Application Lifecycle and Scheduling

**Files:**
- `src/aml/app.py` (update)
- `src/aml/services/monitoring/__init__.py`

**Implementation Details:**
- Register the transactions router in `create_app()`.
- In the `lifespan` startup:
  - Initialise the `MonitoringQueue` consumer as a background task.
  - Register a periodic task (using `asyncio` scheduler or APScheduler) for the `BatchPatternScanner` to run every 15 minutes.
- In the `lifespan` shutdown:
  - Gracefully stop the queue consumer.
  - Cancel the batch scanner task.

**Why:** The monitoring engine must run continuously alongside the API server. The queue consumer processes real-time transactions. The batch scanner catches patterns that accumulate over time. Both are managed by the application lifecycle to ensure clean startup/shutdown.

### Step 7: Implement Tests

**Files:**
- `tests/test_monitoring_rules.py`
- `tests/test_monitoring_evaluator.py`
- `tests/test_monitoring_batch.py`

**Implementation Details:**
- **Rule engine tests:** Verify each operator in `RuleCondition`. Test YAML loading. Test tenant-scoped rule isolation.
- **Evaluator tests:** Mock the rule engine and anomaly scorer. Verify alert creation with correct severity, type, and deduplication. Verify both detection methods are called.
- **Batch scanner tests:** Create a set of transactions in the test DB matching known patterns (structuring, velocity). Verify the scanner detects them and generates appropriate alerts.
- **Integration test:** End-to-end: ingest a transaction via the API → verify it appears in the queue → verify the evaluator processes it → verify the alert is created in the DB.

---

## 4. Default Rule Set (Shipped with Platform)

### 4.1 General Rules (All Entity Types)

| Rule ID | Name | Condition | Alert Type | Severity |
|---------|------|-----------|------------|----------|
| STD-001 | Threshold Reporting | amount >= 10000 AND direction == inbound | `threshold_reporting` | MEDIUM |
| STD-002 | High-Value Wire | amount >= 50000 AND direction == outbound | `high_value_wire` | HIGH |
| STD-003 | High-Risk Jurisdiction | counterparty contains high_risk_countries | `high_risk_jurisdiction` | HIGH |
| STD-004 | Rapid Velocity | tx_count_24h > 10 | `rapid_velocity` | MEDIUM |
| STD-005 | New Counterparty High Value | new_counterparty AND amount >= 5000 | `new_counterparty_high_value` | MEDIUM |

### 4.2 Tranche 2 — Real Estate Rules

| Rule ID | Name | Condition | Alert Type | Severity |
|---------|------|-----------|------------|----------|
| T2RE-001 | Cash Property Purchase | amount >= 10000 AND metadata.settlement_type == "cash" | `cash_property_purchase` | HIGH |
| T2RE-002 | Nominee Purchaser | metadata.purchaser_type == "nominee" | `nominee_purchaser` | HIGH |
| T2RE-003 | Rapid Property Flipping | same property_address sold within 180 days (batch) | `rapid_property_flip` | MEDIUM |
| T2RE-004 | Unexplained Fund Source | amount >= 50000 AND metadata.fund_source == null | `unexplained_fund_source` | MEDIUM |

### 4.3 Tranche 2 — Legal Practice Rules

| Rule ID | Name | Condition | Alert Type | Severity |
|---------|------|-----------|------------|----------|
| T2LG-001 | Trust Account Cash Deposit | metadata.trust_account == true AND direction == inbound AND amount >= 10000 | `trust_cash_deposit` | HIGH |
| T2LG-002 | Non-Client Trust Funds | metadata.trust_account == true AND counterparty not in client_list | `non_client_trust_funds` | HIGH |
| T2LG-003 | Overseas Fund Source | metadata.fund_source == "overseas" AND amount >= 5000 | `overseas_fund_source` | MEDIUM |
| T2LG-004 | Cash Payment for Legal Fees | direction == inbound AND amount >= 5000 AND metadata.payment_type == "cash" | `cash_legal_fees` | MEDIUM |

### 4.4 Tranche 2 — Accounting Practice Rules

| Rule ID | Name | Condition | Alert Type | Severity |
|---------|------|-----------|------------|----------|
| T2AC-001 | Multi-Entity Inter-Transfers | metadata.entity_chain length >= 3 within 48h (batch) | `inter_entity_layering` | HIGH |
| T2AC-002 | Unusual Refund Pattern | direction == inbound AND metadata.type == "refund" AND amount >= 10000 | `unusual_refund` | MEDIUM |
| T2AC-003 | Complex Offshore Structure | metadata.entity_chain contains offshore_jurisdiction | `offshore_structure` | HIGH |

---

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Alert storms** from overly broad rules | High (analyst fatigue) | Deduplication window. Configurable rate limits per rule. Triage (BE-205) auto-clears false positives. |
| **Redis unavailability** | Medium (monitoring stops) | Synchronous fallback in dev mode. Health check endpoint reports queue status. |
| **Batch scanner performance** on large datasets | Medium (query timeout) | Partition scans by tenant. Use indexed queries on `transaction_date` and `tenant_id`. Configurable batch size. |
| **Rule configuration errors** | Medium (missed alerts or storms) | Pydantic validation on rule schemas. Dry-run mode that evaluates rules against historical data without creating alerts. |
