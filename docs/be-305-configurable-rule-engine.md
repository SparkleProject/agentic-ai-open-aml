# BE-305: Configurable Rule Engine — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

BE-206 introduces a basic rule engine for transaction monitoring with hardcoded YAML rules. BE-305 elevates this into a **fully configurable, tenant-scoped rule engine** that compliance officers can manage without code changes.

The engine must:
1. Allow tenants to define custom transaction monitoring rules, thresholds, and typologies via a management API.
2. Support YAML/JSON rule definitions with version control.
3. Enable hot-reloading of rules without application restart.
4. Provide a dry-run mode for testing rules against historical data before activation.
5. Support rule templates for common AML typologies that tenants can adopt and customise.
6. Provide **industry-specific rule template packs** for Tranche 2 entity types (real estate, legal, accounting) that tenants adopt during onboarding based on their business type.

### Tranche 2 Template Pack Strategy

Tranche 2 entities are not banks — they monitor their own business records, not banking transaction feeds. Their "transactions" are trust account movements, property settlements, invoice payments, and inter-entity transfers. The rule engine must ship with template packs tailored to each entity type:

| Entity Type | Template Pack | Key Patterns |
|---|---|---|
| **Real estate** | `T2-REAL-ESTATE` | Cash purchases, nominee buyers, rapid flipping, unexplained fund sources |
| **Legal** | `T2-LEGAL` | Trust account misuse, non-client trust funds, overseas sources, cash fee payments |
| **Accounting** | `T2-ACCOUNTING` | Inter-entity layering, unusual refunds, complex offshore structures |
| **General (all T2)** | `T2-GENERAL` | Threshold reporting, high-risk jurisdiction, velocity, structuring |

During tenant onboarding, the system prompts for the entity type and auto-adopts the matching template pack into the tenant's rule set. Tenants can then customise thresholds and disable irrelevant rules.

### Dependencies on Existing Code
- `src/aml/services/monitoring/rules.py` (created in BE-206) — `MonitoringRule`, `RuleEngine` base classes.
- `src/aml/services/monitoring/evaluator.py` (created in BE-206) — `TransactionEvaluator` that consumes rules.
- `src/aml/db/models/tenant.py` — `Tenant` model with `settings` JSONB.
- `src/aml/core/config.py` — application settings.

---

## 2. Architecture Approach: Versioned Rule Store with Hot-Reload

```
  Rule CRUD API ──> Validation ──> Version Store (DB) ──> Rule Cache (Redis) ──> Evaluator
                                        │                       ▲
                                        │                       │
                                  Version History         Hot-Reload Signal
                                  (audit trail)           (pub/sub)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Rule Storage Models

**Files:**
- `src/aml/db/models/rule.py`

**Implementation Details:**
- Define `TenantRule` ORM model extending `TenantMixin, Base`:
  - `tenant_id: str` (FK)
  - `rule_id: str` — human-readable identifier (e.g., `CUST-001`)
  - `name: str`
  - `description: str`
  - `category: str` — typology category (structuring, sanctions, velocity, trust_account, property, custom)
  - `entity_type: str | None` — target Tranche 2 entity type (real_estate, legal, accounting, or None for general)
  - `conditions: dict` (JSONB) — the rule condition tree
  - `alert_type: str`
  - `severity: AlertSeverity`
  - `enabled: bool = True`
  - `version: int = 1`
  - `is_template: bool = False` — marks rules in the shared template library
  - `parent_template_id: str | None` — if this rule was adopted from a template
- Define `RuleVersion` ORM model for version history:
  - `rule_id: UUID` (FK to `tenant_rules.id`)
  - `version: int`
  - `conditions_snapshot: dict` (JSONB) — frozen copy of conditions at this version
  - `changed_by: str`
  - `change_reason: str | None`

**Why:** Database-backed rule storage supports CRUD operations, version history, and tenant isolation. The version table provides an audit trail showing who changed what and when — critical for regulatory compliance.

### Step 2: Extend the Rule Condition DSL

**Files:**
- `src/aml/services/monitoring/rules.py` (update from BE-206)

**Implementation Details:**
- Extend `RuleCondition` to support:
  - **Logical operators**: `AND`, `OR`, `NOT` for combining conditions.
  - **Aggregation operators**: `SUM`, `COUNT`, `AVG` over a time window (e.g., `COUNT(transactions, 24h) > 5`).
  - **Cross-field conditions**: compare two fields on the transaction (e.g., `amount > customer.avg_transaction * 3`).
  - **Temporal conditions**: `WITHIN(24h)`, `SINCE(last_transaction)`.
  - **List membership**: `IN(high_risk_countries)`, `NOT_IN(whitelisted_counterparties)`.
- Implement `RuleConditionEvaluator`:
  - `evaluate(condition: RuleCondition, context: EvaluationContext) -> bool`
  - `EvaluationContext` contains: the transaction, customer profile, historical aggregates, and tenant settings.
  - Supports nested condition trees via recursive evaluation.
- Validate conditions at creation time — reject syntactically invalid conditions before storage.

**Why:** A basic field-comparison rule engine (BE-206) cannot express complex AML typologies like "3 or more cash deposits under $10,000 to the same counterparty within 48 hours." The DSL extension enables these patterns while remaining declarative and auditable.

### Step 3: Implement Rule CRUD Service

**Files:**
- `src/aml/services/monitoring/rule_management.py`

**Implementation Details:**
- Implement `RuleManagementService`:
  - `async create_rule(tenant_id: str, rule: CreateRuleRequest) -> TenantRule`:
    - Validates conditions via `RuleConditionEvaluator` (syntax check).
    - Persists to DB with version 1.
    - Publishes cache invalidation signal.
  - `async update_rule(rule_id: UUID, updates: UpdateRuleRequest, changed_by: str) -> TenantRule`:
    - Creates a `RuleVersion` snapshot of the previous state.
    - Increments `version`.
    - Re-validates conditions.
    - Publishes cache invalidation.
  - `async delete_rule(rule_id: UUID)` — soft delete (sets `enabled = False`).
  - `async list_rules(tenant_id: str, category: str | None) -> list[TenantRule]`.
  - `async get_rule(rule_id: UUID) -> TenantRule` with version history.
  - `async adopt_template(tenant_id: str, template_id: str) -> TenantRule` — copies a global template into the tenant's rule set for customisation.

**Why:** CRUD operations are the management interface. Versioning ensures no rule change is lost. Template adoption enables the platform to ship recommended rules that tenants can customise.

### Step 4: Build Rule Cache and Hot-Reload

**Files:**
- `src/aml/services/monitoring/rule_cache.py`

**Implementation Details:**
- Implement `RuleCache`:
  - Backed by Redis (using the existing `redis_url`).
  - `async load_rules(tenant_id: str) -> list[MonitoringRule]`:
    - First checks Redis. If cached, returns immediately.
    - If miss, loads from DB, converts to `MonitoringRule` format, caches with TTL (5 minutes).
  - `async invalidate(tenant_id: str)`:
    - Deletes the cache entry.
    - Publishes a `rule_updated:{tenant_id}` message on Redis pub/sub.
  - On startup, subscribes to `rule_updated:*` events and invalidates local in-memory cache.
- Update `TransactionEvaluator` (BE-206) to load rules through `RuleCache` instead of directly from YAML.
- **Fallback**: if Redis is unavailable, loads directly from DB on every evaluation (slower but functional).

**Why:** Hot-reload is essential because compliance officers update rules during business hours. A rule change must take effect within seconds, not after a deployment. Redis caching prevents hitting the database on every transaction evaluation.

### Step 5: Implement Dry-Run Mode

**Files:**
- `src/aml/services/monitoring/dry_run.py`

**Implementation Details:**
- Implement `RuleDryRunService`:
  - `async dry_run(rule: MonitoringRule, tenant_id: str, window_hours: int = 168) -> DryRunReport`:
    - Loads historical transactions for the tenant within the time window.
    - Evaluates the rule against each transaction.
    - Returns a `DryRunReport`:
      - `total_transactions_evaluated: int`
      - `matches: int`
      - `match_rate: float`
      - `sample_matches: list[dict]` — first 20 matched transactions with details.
      - `estimated_alerts_per_day: float`
      - `severity_distribution: dict[str, int]`
  - Does NOT create any actual alerts.

**Why:** Without dry-run, a misconfigured rule could generate hundreds of false-positive alerts. Dry-run lets compliance officers see the impact of a rule before enabling it — critical for operational confidence and preventing alert fatigue.

### Step 6: Create Rule Management API

**Files:**
- `src/aml/api/routers/rules.py`

**Implementation Details:**
- `POST /api/v1/rules` — Create a new tenant rule. Body: rule definition JSON.
- `GET /api/v1/rules` — List rules for the tenant. Query params: `category`, `enabled`.
- `GET /api/v1/rules/{rule_id}` — Get rule details with version history.
- `PUT /api/v1/rules/{rule_id}` — Update a rule. Requires `change_reason` in body.
- `DELETE /api/v1/rules/{rule_id}` — Soft delete (disable).
- `POST /api/v1/rules/{rule_id}/dry-run` — Run the rule against historical data.
- `GET /api/v1/rules/templates` — List available rule templates.
- `POST /api/v1/rules/templates/{template_id}/adopt` — Adopt a single template into the tenant's rule set.
- `POST /api/v1/rules/template-packs/{pack_name}/adopt` — Bulk-adopt an entire template pack (e.g., `T2-REAL-ESTATE`). Used during tenant onboarding.
- `GET /api/v1/rules/template-packs` — List available template packs with descriptions and rule counts.
- Register in `app.py`.

**Why:** These endpoints enable the future FE rule management UI and allow programmatic rule management via the API.

### Step 7: Ship Default Rule Templates

**Files:**
- `src/aml/services/monitoring/default_templates.py`

**Implementation Details:**
- Define global rule templates in **four packs**, grouped by `entity_type`:

**`T2-GENERAL` pack (all entity types):**
  - **Structuring**: Multiple sub-threshold transactions within 48 hours.
  - **Rapid movement**: High transaction velocity exceeding customer baseline.
  - **High-risk jurisdiction**: Transactions involving FATF-listed jurisdictions.
  - **Dormant account activity**: Transactions on accounts with no activity for >90 days.
  - **Round-amount deposits**: Large round-number cash deposits.
  - **Smurfing**: Multiple small deposits across accounts linked to same beneficiary.

**`T2-REAL-ESTATE` pack:**
  - **Cash property purchase**: Cash settlement >= $10,000 (via `metadata_.settlement_type`).
  - **Nominee purchaser**: Purchaser flagged as nominee (via `metadata_.purchaser_type`).
  - **Rapid property flipping**: Same property address sold/bought within 180 days (batch pattern).
  - **Unexplained fund source**: High-value transaction with no documented fund source.

**`T2-LEGAL` pack:**
  - **Trust account cash deposit**: Inbound cash >= $10,000 to trust account (via `metadata_.trust_account`).
  - **Non-client trust funds**: Trust account receiving funds from counterparty not in the firm's client list.
  - **Overseas fund source**: Funds originating from overseas (via `metadata_.fund_source`).
  - **Cash payment for legal fees**: Cash fee payment >= $5,000.

**`T2-ACCOUNTING` pack:**
  - **Inter-entity layering**: Client with 3+ related entities moving funds between them within 48 hours (via `metadata_.entity_chain`).
  - **Unusual refund pattern**: Large refunds not matching typical client profile.
  - **Complex offshore structure**: Entity chain includes offshore jurisdictions.

- Implement `seed_default_templates(entity_type: str | None = None)`:
  - Called during app startup to ensure templates exist in the DB.
  - Always seeds `T2-GENERAL`. Optionally seeds entity-specific packs.
- Implement `adopt_template_pack(tenant_id: str, pack_name: str)`:
  - Bulk-adopts all rules in a pack into the tenant's rule set.
  - Called during tenant onboarding after entity type is selected.

**Why:** Tranche 2 entities are not banks — they need monitoring rules tailored to their specific business operations (trust accounts, property settlements, inter-entity flows). A real estate agent has zero use for banking wire-fraud rules, but critically needs nominee purchaser detection. Template packs grouped by entity type provide immediate, relevant value during onboarding without overwhelming the tenant with irrelevant rules.

### Step 8: Implement Tests

**Files:**
- `tests/test_rule_management.py`
- `tests/test_rule_dry_run.py`

**Implementation Details:**
- Test CRUD operations: create, update (verify versioning), delete (verify soft delete).
- Test condition DSL: AND/OR/NOT combinations, aggregation operators, temporal conditions.
- Test cache invalidation: update a rule, verify the cache is refreshed.
- Test dry-run: create a rule, seed test transactions, verify match count and sample output.
- Test template adoption: adopt a template, verify it's cloned into the tenant's rule set.
- Test pack adoption: adopt `T2-REAL-ESTATE` pack, verify all 4 real estate rules are created for the tenant.
- Test metadata-based conditions: create a rule checking `metadata_.trust_account == true`, evaluate against transactions with and without the metadata field.
- Test entity-type filtering: verify a legal-practice tenant only sees `T2-GENERAL` and `T2-LEGAL` packs as recommended.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Complex rule conditions causing evaluation slowdown** | Medium | Condition evaluation timeout (500ms per rule). Performance metrics per rule. |
| **Rule conflicts** (overlapping rules generating duplicate alerts) | Medium | Rule overlap detection during creation. Deduplication in the evaluator (BE-206). |
| **Cache inconsistency** across multiple app instances | Medium | Redis pub/sub ensures all instances invalidate simultaneously. |
| **Audit trail gaps** if versioning is bypassed | High | All mutations go through `RuleManagementService` — no direct DB writes from the API. |
