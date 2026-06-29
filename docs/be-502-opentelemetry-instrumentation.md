# BE-502: OpenTelemetry Instrumentation — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

The platform currently logs via structlog with JSON output. This provides application-level visibility but lacks:
- **Distributed tracing**: no correlation of a single investigation across planner → reasoner → actor → reflector nodes, tool calls, RAG retrievals, and LLM invocations.
- **Metrics**: no quantitative dashboards for latency percentiles, throughput, error rates, or cost.
- **Span-level detail**: no visibility into which step in an agent loop is the bottleneck.

BE-502 integrates **OpenTelemetry (OTel)** to provide production-grade observability across all platform components.

### Dependencies on Existing Code
- `src/aml/agents/nodes.py` — agent nodes to instrument with spans.
- `src/aml/agents/tools/registry.py` — tool execution to trace.
- `src/aml/services/llm/protocol.py` — LLM calls to measure latency and token counts.
- `src/aml/services/rag/service.py` — RAG queries to trace.
- `src/aml/services/vector_db/milvus.py` — vector DB operations to measure.
- `src/aml/app.py` — FastAPI app for HTTP request tracing.

### Frontend Context
- `src/pages/ObservabilityDashboard.tsx` — displays throughput, latency P50/P95/P99, error rate, cost. Currently uses `mockObservabilityData.ts`. Must be wired to real metrics endpoints.

---

## 2. Architecture Approach: OTel SDK with Custom LLM Spans

```
  FastAPI Request ──> OTel Middleware ──> Agent Spans ──> Tool Spans ──> LLM Spans ──> OTel Collector
                     (HTTP traces)       (planner,        (screening,   (model, tokens,  (export to
                                          reasoner,        transactions)  latency)         Grafana/CW)
                                          actor, reflector)
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Set Up OpenTelemetry SDK and Configuration

**Files:**
- `src/aml/observability/setup.py`
- `src/aml/core/config.py` (update)

**Implementation Details:**
- Add OTel settings to `Settings`:
  - `otel_enabled: bool = False`
  - `otel_service_name: str = "aml-platform"`
  - `otel_exporter: str = "console"` — `console`, `otlp`, `cloudwatch`
  - `otel_otlp_endpoint: str = "http://localhost:4317"` — for OTLP gRPC exporter
  - `otel_sample_rate: float = 1.0` — 1.0 = trace everything, 0.1 = sample 10%
- Implement `setup_telemetry(settings: Settings)`:
  - Configures the OTel `TracerProvider` with:
    - Service name and version.
    - Resource attributes (environment, tenant context).
    - Exporter based on settings (console for dev, OTLP for staging/prod).
    - Sampler based on `otel_sample_rate`.
  - Configures the `MeterProvider` for metrics:
    - Custom meters for LLM-specific metrics (token counts, cost, latency).
  - Returns a configured `tracer` and `meter` for use across the application.
- Called during app `lifespan` startup.

**Why:** OTel provides vendor-neutral instrumentation. The same code works with Grafana, Datadog, AWS CloudWatch, or any OTLP-compatible backend. Console exporter enables local development debugging.

### Step 2: Instrument FastAPI with HTTP Tracing

**Files:**
- `src/aml/app.py` (update)

**Implementation Details:**
- Add `opentelemetry-instrumentation-fastapi` auto-instrumentation:
  - Automatically creates spans for every HTTP request.
  - Captures: method, path, status code, latency.
  - Propagates trace context from incoming `traceparent` headers.
- Add custom span attributes:
  - `tenant_id` from the request context.
  - `request_id` from the `X-Request-ID` header.
- Create custom HTTP metrics:
  - `http_requests_total` counter (by method, path, status).
  - `http_request_duration_seconds` histogram.

**Why:** HTTP-level tracing is the entry point. Every API request gets a trace ID that propagates through all downstream operations, creating a complete picture of the request lifecycle.

### Step 3: Instrument Agent Orchestrator Nodes

**Files:**
- `src/aml/observability/agent_spans.py`
- `src/aml/agents/nodes.py` (update)

**Implementation Details:**
- Create `agent_span` context manager/decorator:
  ```python
  @contextmanager
  def agent_span(name: str, attributes: dict | None = None):
      tracer = get_tracer()
      with tracer.start_as_current_span(f"agent.{name}") as span:
          if attributes:
              for k, v in attributes.items():
                  span.set_attribute(k, v)
          yield span
  ```
- Wrap each agent node:
  - `planner_node`: span `agent.planner` with attributes: `alert_id`, `severity`.
  - `reasoner_node`: span `agent.reasoner` with attributes: `active_agent`, `decision`.
  - `actor_node`: span `agent.actor` with attributes: `tool_name`, `tool_result_length`.
  - `delegator_node`: span `agent.delegator` with attributes: `target_agent`, `reason`.
  - `reflector_node`: span `agent.reflector` with attributes: `conclusion_status`.
- Create agent-level metrics:
  - `agent_investigations_total` counter (by agent type, outcome).
  - `agent_loop_iterations` histogram (how many loops before conclusion).
  - `agent_investigation_duration_seconds` histogram.

**Why:** Agent spans reveal the investigation flow: which nodes were visited, how many loop iterations occurred, and where time was spent. This is critical for debugging slow investigations and detecting infinite loops.

### Step 4: Instrument LLM Provider Calls

**Files:**
- `src/aml/observability/llm_spans.py`
- `src/aml/services/llm/factory.py` (update)

**Implementation Details:**
- Create `TracedLLMProvider` wrapper (decorator pattern, like `GuardedLLMProvider`):
  - Wraps `generate_response()` with a span `llm.generate`:
    - Attributes: `llm.model_id`, `llm.provider`, `llm.temperature`, `llm.prompt_length`.
    - Events: `llm.response_received` with `response_length`.
    - Metrics:
      - `llm_tokens_input` counter.
      - `llm_tokens_output` counter.
      - `llm_latency_seconds` histogram (by model, purpose).
      - `llm_cost_usd` counter (estimated from token counts and model pricing).
      - `llm_errors_total` counter (by error type).
  - The wrapper chains with `GuardedLLMProvider`: `TracedLLMProvider(GuardedLLMProvider(actual_provider))`.
- Update `get_llm_provider()` to wrap with tracing when `otel_enabled`.

**Why:** LLM calls are the most expensive and variable-latency operations. Per-model metrics reveal cost distribution, latency outliers, and error patterns. Token counters enable the cost tracking dashboard.

### Step 5: Instrument RAG and Vector DB

**Files:**
- `src/aml/services/rag/service.py` (update)
- `src/aml/services/vector_db/milvus.py` (update)

**Implementation Details:**
- RAG service instrumentation:
  - `rag.ingest` span: attributes `tenant_id`, `source`, `chunk_count`.
  - `rag.query` span: attributes `tenant_id`, `question_length`, `hits`, `hybrid_mode`.
  - Metrics: `rag_queries_total`, `rag_query_latency_seconds`, `rag_chunks_ingested_total`.
- Milvus vector DB instrumentation:
  - `vectordb.upsert` span: attributes `collection`, `count`.
  - `vectordb.search` span: attributes `collection`, `mode` (dense/hybrid), `hits`.
  - Metrics: `vectordb_operations_total` (by operation type), `vectordb_latency_seconds`.

**Why:** RAG and vector DB performance directly impacts investigation latency. Hybrid search mode comparisons (dense vs. hybrid latency) inform optimisation decisions.

### Step 6: Instrument Tool Registry Execution

**Files:**
- `src/aml/agents/tools/registry.py` (update)

**Implementation Details:**
- Wrap `ToolRegistry.execute()` with a span `tool.execute`:
  - Attributes: `tool.name`, `tool.success`, `tool.result_length`.
  - Metrics: `tool_executions_total` (by tool name, success/failure), `tool_latency_seconds`.
- For MCP proxy tools, add `tool.external` flag and `tool.endpoint` attribute.

**Why:** Tool execution latency varies widely (mock tools are instant, MCP proxy calls can take seconds). Instrumentation reveals which tools are bottlenecks.

### Step 7: Create Observability API Endpoints

**Files:**
- `src/aml/api/routers/observability.py`

**Implementation Details:**
- `GET /api/v1/observability/metrics` — Returns aggregated metrics for the FE dashboard:
  - Response matches `ObservabilityData` shape expected by `ObservabilityDashboard.tsx`:
    - `summary`: `totalProcessed`, `activeAgents`, `currentErrorRate`, `costMonthToDate`.
    - `metrics`: time-series array of `{ time, p50LatencyMs, p95LatencyMs, p99LatencyMs, throughput, errorRate, averageCostUSD }`.
  - Queries the OTel metrics backend or the governance log aggregations.
- `GET /api/v1/observability/traces/{trace_id}` — Returns the full trace for an investigation.
- `GET /api/v1/observability/health` — System health: queue depth, active agents, DB connection pool, Milvus status.
- Register in `app.py`.

**Why:** The FE `ObservabilityDashboard.tsx` needs real data. The metrics endpoint replaces `mockObservabilityData.ts`. The trace endpoint enables deep investigation debugging.

### Step 8: Implement Tests

**Files:**
- `tests/test_observability.py`

**Implementation Details:**
- Test span creation: run an agent investigation, verify spans are created for each node.
- Test LLM metrics: verify token counters increment correctly.
- Test trace propagation: verify parent-child span relationships (HTTP → agent → tool → LLM).
- Test sampling: set sample rate to 0.0, verify no spans are created.
- Test metrics endpoint: verify response shape matches FE expectations.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **OTel overhead on latency** | Low | Sampling rate for high-throughput paths. Async span export. |
| **Trace data volume** in production | Medium | Configurable sample rate. Head-based sampling. 7-day retention in collector. |
| **OTel collector availability** | Medium | Graceful degradation: if collector is down, spans are dropped, app continues. |
| **Sensitive data in span attributes** | High | Never include prompt content in span attributes. Use hashes or length only. PII redaction applies. |
