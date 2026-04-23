# ADK Agents Observability & Telemetry Guide

This document provides a comprehensive overview of the observability stack in the ADK Agents application. It covers everything from infrastructure-level distributed tracing (OpenTelemetry) to tracking specific business domain logic (Custom Metrics).

---

## 1. Architecture & Data Flow

The observability stack bridges the gap between raw infrastructure telemetry (like API latencies) and business domain logic (like Human-in-the-Loop escalations). 

It relies on **OpenTelemetry**, **OpenLLmetry** (for Google GenAI auto-instrumentation), and a custom ADK **TelemetryPlugin** to seamlessly intercept the agent lifecycle without cluttering the core agent code.

### 1.1 The Request Lifecycle

```text
      [User Request] ──▶ [ADK Runner / Orchestrator]
                                │
                                ├─▶ [TelemetryPlugin: before_model] (Starts OTel Span)
                                │
                                ▼
                        [Gemini API / Tool]
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
            [✅ SUCCESS]                  [❌ ERROR / BLOCK]
                 │                             │
                 ▼                             ▼
  [TelemetryPlugin: after_model]   [SystemAndRuntimeMetrics]
  - End Span (status=OK)           - End Span (status=ERROR)
  - Compute Cost USD               - Categorize Error (e.g., rate_limit)
  - Aggregate Total Tokens         - Emit to errors.by_category (Counter)
                                   - Trigger @with_retry loop
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
           [OpenTelemetry Exporter (GCP Trace, Jaeger, Dynatrace)]
```

### 1.2 Trace Hierarchy (Distributed Context)

To stitch logs, spans, and metrics together, the system tracks multiple IDs throughout the async lifecycle:

*   **`trace_id`**: The standard OpenTelemetry trace ID generated when the HTTP request hits FastAPI. Groups the entire flame graph.
*   **`span_id`**: The specific operation currently executing.
*   **`correlation_id`**: Your business transaction ID (`corr-{invocation_id}`). Links spans together across agents, tools, and custom metrics.
*   **`causation_id`**: Tracks parent-child relationships (e.g., the orchestrator span ID becomes the causation ID for the sub-agent span).

---

## 2. Exporters & Configuration

You can seamlessly route your traces and metrics to different observability backends by changing a few environment variables. No code changes are required.

### 2.1 Quick Reference

| Exporter | Environment Variables | Where Traces Appear |
|----------|----------------------|---------------------|
| **Console** (Local) | `OTEL_EXPORTER_TYPE=console` | stdout (Terminal) |
| **GCP Cloud Trace** | `OTEL_EXPORTER_TYPE=gcp` + `GOOGLE_CLOUD_PROJECT=prj-id` | GCP Console → Trace |
| **Jaeger** (Local) | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` | http://localhost:16686 |
| **Dynatrace** | `OTEL_EXPORTER_TYPE=otlp` + `...ENDPOINT=https://your-env.live.dynatrace.com/api/v2/otlp` | Dynatrace UI |
| **Datadog** | `OTEL_EXPORTER_TYPE=otlp` + `...HEADERS=dd-protocol=otlp,dd-api-key=KEY` | Datadog UI |

### 2.2 Global Settings

*   `OTEL_ENABLED`: `true` or `false`
*   `OTEL_SERVICE_NAME`: The name of the service (default: `adk-agents`)
*   `OTEL_STRUCTURED_LOGS`: `true` outputs Cloud Logging compatible JSON logs with trace IDs injected. `false` uses colored, emoji-based terminal output.

---

## 3. Core Infrastructure Metrics

The `TelemetryPlugin` and OpenLLmetry automatically capture standard operational metrics for every LLM and Tool invocation.

### 3.1 LLM Metrics
*   `llm.input_tokens` / `llm.output_tokens` (Counters)
*   `llm.latency` (Histogram)
*   `llm.cost_usd` (Counter) - Automatically calculated using cached pricing data from LiteLLM.
*   `llm.errors` (Counter)

### 3.2 Tool Metrics
*   `tool.calls` (Counter)
*   `tool.latency` (Histogram)
*   `tool.errors` (Counter)

### 3.3 Dynamic Cost Tracking
LLM costs are calculated seamlessly:
1. **Auto-fetches pricing** from LiteLLM's GitHub repository via a background thread on server startup.
2. **Caches for 24 hours**.
3. Overrides available via environment variables (e.g., `LLM_PRICE_FLASH_INPUT=0.075`).

---

## 4. Custom Business Metrics (Domain Taxonomy)

Instead of scattering raw metric emissions throughout the codebase, ADK Agents organizes custom metrics into **5 Domain Classes** that precisely map to our business alerting strategy.

### 4.1 System & Runtime Metrics (`SystemAndRuntimeMetrics`, `RetryTracker`)
Automatically categorizes API failures and triggers exponential backoff.

**Tracked Error Categories:** `rate_limit`, `timeout`, `authentication`, `authorization`, `resource_exhausted`, `internal_error`.

```python
from adk_web_api.custom_metrics import SystemAndRuntimeMetrics

try:
    result = flaky_api_call()
except Exception as e:
    # Automatically categorizes the error based on code/message
    categorized = SystemAndRuntimeMetrics.record_and_categorize(error=e, correlation_id="corr-123")
    
    if categorized.is_retryable:
        print(f"Safe to retry in {categorized.suggested_backoff_ms}ms")
```
*Note: Agent invocations can automatically utilize this using the `@with_retry(max_retries=3)` decorator.*

### 4.2 HITL Operations Metrics (`HITLOperationsMetrics`)
Used when an AI lacks confidence and escalates a task to a human agent queue.

```python
from adk_web_api.custom_metrics import HITLOperationsMetrics

# Record when an AI escalates a task
HITLOperationsMetrics.record_escalation(
    escalation_type="low_confidence",
    reason="Sentiment analysis fell below 0.6",
    agent_id="orchestrator"
)

# Record the completion of a human review
HITLOperationsMetrics.record_review_completed(
    reviewer_id="agent_smith",
    duration_ms=45000,     # Time taken by human to review
    queue_time_ms=120000,  # Time spent waiting in the queue
    decision="override"
)
```

### 4.3 Governance & Quality Metrics (`GovernanceAndQualityMetrics`)
Emitted automatically by the DLP plugin or evaluator agents when processing data.

```python
from adk_web_api.custom_metrics import GovernanceAndQualityMetrics

# Automatically triggered by DLP Plugin when PII is masked
GovernanceAndQualityMetrics.record_pii_detected(
    info_type="US_SOCIAL_SECURITY_NUMBER",
    action_taken="mask",
    use_case="user_message"
)

# Record safety violations
GovernanceAndQualityMetrics.record_safety_trigger(
    trigger_reason="PROMPT_INJECTION",
    channel="web_chat"
)

# Record groundedness/relevance score of an agent's response
GovernanceAndQualityMetrics.record_groundedness(
    score=0.92,
    use_case="knowledge_search",
    subagent_id="support_agent",
    attributes={"query": "return policy"}
)
```

### 4.4 Secret Manager Metrics (`SecretManagerMetrics`)
Tracks GCP Secret Manager load latencies and initialization errors.

---

## 5. Adding Your Own Metrics

There are two ways to extend the metrics system depending on the scope of your feature.

### 5.1 Quick Method: `CustomMetricsRegistry`
For simple, one-off events (like a tool execution tracking search queries).

```python
from adk_web_api.custom_metrics import CustomMetricsRegistry

registry = CustomMetricsRegistry.get_instance()

# 1. Register it (e.g., at module load)
if not registry.is_registered("store_locator.searches"):
    registry.register_counter(
        name="store_locator.searches",
        description="Number of times a user searched for a store"
    )

# 2. Emit it
registry.emit_counter("store_locator.searches", value=1, attributes={
    "zip_code": "90210",
    "found_results": "true"
})
```

### 5.2 Scalable Method: Creating a New Domain Class
If you are building a massive feature (e.g., an Order Management agent), create a dedicated class inside `custom_metrics.py`.

```python
# 1. Define inside custom_metrics.py
class OrderMetrics:
    _order_counter = None

    @classmethod
    def initialize(cls, meter):
        cls._order_counter = meter.create_counter("business.orders", unit="orders")

    @classmethod
    def record_order(cls, status: str, amount_tier: str):
        if cls._order_counter:
            cls._order_counter.add(1, {"status": status, "amount_tier": amount_tier})

# 2. Register inside CustomMetricsRegistry.initialize_all()
# OrderMetrics.initialize(meter)
```

---

## 6. Viewing Data & Alerting

### 6.1 Viewing Traces Locally (Jaeger)
1. Start the Jaeger container:
   ```bash
   docker run -d -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one:latest
   ```
2. Set environment variables:
   ```bash
   export OTEL_EXPORTER_TYPE=otlp
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   ```
3. Run the application and open `http://localhost:16686` to see the full flame graph of agent delegations.

### 6.2 Viewing Metrics Locally
Use `OTEL_EXPORTER_TYPE=console`. 
**⚠️ Important:** OpenTelemetry batches metrics to save network bandwidth. Metric JSON blocks will print to your terminal exactly every **60 seconds**, or instantly if you safely terminate the app (`Ctrl+C`).

### 6.3 Setting Up Alerts in Production (GCP / Dynatrace)
Because OpenTelemetry `Counters` export as `CUMULATIVE` metrics, they continuously increase over time. To alert when an event happens, query the **delta (rate of change)**.

**Example: GCP MQL to alert on `hitl.sla_breaches` > 0 in a 1-minute window:**
```mql
fetch cloud_run_revision
| metric 'custom.googleapis.com/hitl.sla_breaches'
| align delta(1m)
| every 1m
| condition val() > 0
```

**Example: GCP MQL to alert if `rate_limit` errors spike > 5 per minute:**
```mql
fetch cloud_run_revision
| metric 'custom.googleapis.com/errors.by_category'
| filter (metric.category == 'rate_limit')
| align delta(1m)
| every 1m
| condition val() > 5
```

### 6.4 Querying Span Attributes (GCP Trace)
In GCP Cloud Trace or Datadog, you can filter your traces using the custom attributes injected by the `TelemetryPlugin`.
*   Find all operations for a specific session: `attributes.session_id: "api_session"`
*   Find all failing routing decisions: `attributes.call_type: "agent_routing" AND attributes.success: "false"`