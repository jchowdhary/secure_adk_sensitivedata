# Custom Metrics & Observability Guide

The `custom_metrics.py` module bridges the gap between raw infrastructure telemetry (like CPU usage or LLM latency) and your **business domain logic**. 

We have organized metrics into **Domain Classes** to prevent code clutter and make it extremely clear *which* method you should call based on *what* you are trying to track.

---

## 🏗️ Architecture & Data Flow

### 1. Telemetry Plugin Flow (Success vs. Error)
When an agent interacts with external systems (like LLMs or Tools), the telemetry plugin intercepts the lifecycle to track both successful executions and catastrophic failures seamlessly.
Additionally, OpenLLmetry instruments Google GenAI directly.

```text
      [User Request] ──▶ [ADK Runner / Orchestrator]
                                │
                                ├─▶ [TelemetryPlugin: before_model] (Starts Span)
                                │
                                ▼
                        [Gemini API / Tool]
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
            [✅ SUCCESS]                  [❌ ERROR / BLOCK]
                 │                             │
                 ▼                             ▼
  [TelemetryPlugin: after_model]   [TelemetryPlugin / ErrorMetrics]
  - End Span (status=OK)           - End Span (status=ERROR)
  - Compute Cost USD               - Categorize Error (e.g., rate_limit)
  - Aggregate Total Tokens         - errors.by_category (Counter)
                                   - Trigger @with_retry
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
           [OpenTelemetry Exporter (GCP Trace / Dynatrace)]
```

### 2. Custom Metrics Domain Taxonomy
Instead of scattering raw metric calls throughout the application, our architecture groups metrics into distinct business domains that all feed into the underlying OpenTelemetry registry.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CustomMetricsRegistry                           │
│         (Singleton managing the OpenTelemetry Meter & Exports)         │
└────▲──────────────────▲──────────────────▲───────────────────▲─────────┘
     │                  │                  │                   │
┌────┴─────────┐ ┌──────┴─────────┐ ┌──────┴──────────┐ ┌──────┴─────────┐
│ ErrorMetrics │ │ Governance &   │ │ HITLMetrics     │ │ SecretManager  │
│ & Trackers   │ │ QualityMetrics │ │                 │ │ Metrics        │
├──────────────┤ ├────────────────┤ ├─────────────────┤ ├────────────────┤
│ • Errors by  │ │ • PII Detected │ │ • Escalations   │ │ • Secret Loads │
│   Category   │ │ • Safety Blocks│ │ • Queue Wait    │ │ • Load Latency │
│ • Retries    │ │ • Cache Events │ │ • Review Time   │ │ • Load Errors  │
│ • Fallbacks  │ │ • Groundedness │ │ • SLA Breaches  │ │                │
└──────────────┘ └────────────────┘ └─────────────────┘ └────────────────┘
        ▲                ▲                  ▲                   ▲
        │                │                  │                   │
   (Triggered       (Triggered by      (Triggered by       (Triggered by
    by API          DLP Plugin or        Routing           Startup Logic)
   Failures)      Evaluator Agents)    Decisions)
```

---

## 🧠 The Decision Tree: Which class should I use?

Ask yourself: **"What kind of event am I trying to track right now?"**

| Event Type | Class to Use | Example Scenario |
| :--- | :--- | :--- |
| **Data Quality / Safety** | `GovernanceAndQualityMetrics` | PII was masked, or LLM output was flagged for safety. |
| **Human Review** | `HITLMetrics` | An agent escalated a decision to a human queue. |
| **Failures & Fallbacks** | `ErrorMetrics` / `RetryTracker` | An API timed out, or a model downgraded to Flash. |
| **Google Cloud Secrets** | `SecretManagerMetrics` | A secret failed to load from GCP. |
| **Ad-hoc Business Logic** | `CustomMetricsRegistry` | User completed checkout, or a promo code was applied. |

---

## 1. Using Domain Metrics (Best Practice)

Whenever you are working within a recognized domain (like Governance or HITL), you should import that specific class and call its explicit methods. You don't need to worry about metric names or OpenTelemetry configurations—the class handles it.

### Example: Tracking a Safety or Quality Event
```python
from adk_web_api.custom_metrics import GovernanceAndQualityMetrics

# The output was verified against facts, log the score
GovernanceAndQualityMetrics.record_groundedness(
    score=0.95, 
    use_case="customer_support",
    subagent_id="refund_agent"
)

# A safety block was triggered
GovernanceAndQualityMetrics.record_safety_trigger(
    trigger_reason="PROMPT_INJECTION",
    channel="web_chat"
)
```

### Example: Tracking Human-in-the-Loop (HITL)
```python
from adk_web_api.custom_metrics import HITLMetrics

# The AI lacks confidence and escalates to a human
HITLMetrics.record_escalation(
    escalation_type="low_confidence",
    reason="Sentiment analysis fell below 0.6",
    agent_id="orchestrator"
)
```

### Example: Categorizing and Tracking an Error
```python
from adk_web_api.custom_metrics import ErrorMetrics

try:
    result = my_flaky_api_call()
except Exception as e:
    # Automatically categorizes the error (e.g., Timeout, Auth, Rate Limit)
    # and logs it to your metrics dashboard.
    categorized = ErrorMetrics.record_and_categorize(
        error=e,
        correlation_id="corr-abc-123"
    )
    
    if categorized.is_retryable:
        print(f"Retrying in {categorized.suggested_backoff_ms} ms...")
```

---

## 2. Using the `CustomMetricsRegistry` (For One-Off Business Events)

If you are building a new feature (e.g., a "Store Locator" tool) and want to track a metric quickly without creating a whole new Domain Class, use the `CustomMetricsRegistry`.

```python
from adk_web_api.custom_metrics import CustomMetricsRegistry

registry = CustomMetricsRegistry.get_instance()

# 1. Register it (Do this once, e.g., at module load or startup)
if not registry.is_registered("store_locator.searches"):
    registry.register_counter(
        name="store_locator.searches",
        description="Number of times a user searched for a store",
        unit="searches"
    )

# 2. Emit it whenever the tool runs
registry.emit_counter("store_locator.searches", value=1, attributes={
    "zip_code": "90210",
    "found_results": "true"
})
```

---

## 3. Creating a New Domain Class (For Scaling)

If your new feature grows complex (e.g., you are building a massive "Order Management" agent with many different metrics), **do not** clutter your business logic with raw `registry.emit_counter` calls. 

Instead, look at how `HITLMetrics` is built inside `custom_metrics.py`. 
1. Create a `class OrderManagementMetrics:` inside `custom_metrics.py`.
2. Add class variables for your `_counters` and `_histograms`.
3. Create an `initialize(cls, meter)` method.
4. Add it to `CustomMetricsRegistry.initialize_all()`.

This keeps the codebase incredibly clean and gives your team strict, typed methods to call (e.g., `OrderManagementMetrics.record_refund_issued()`).

---

## 4. How to View Your Custom Metrics

### Viewing Locally (Console Exporter)
The console exporter is the easiest way to verify your metrics are working during local development.

```bash
export OTEL_EXPORTER_TYPE=console
uvicorn adk_web_api.main:app
```

**⚠️ Important Note on Timing:**
By default, OpenTelemetry batches metrics to save network bandwidth and exports them every **60 seconds**. 
* When your code emits a custom metric, it will not print immediately.
* Wait up to 60 seconds (or cleanly shut down the app with `Ctrl+C` to force a flush), and you will see a JSON block print to your terminal like this:

```json
{
    "name": "hitl.escalations",
    "description": "Number of escalations to a human reviewer",
    "unit": "events",
    "data": {
        "data_points": [
            {
                "attributes": {"escalation_type": "low_confidence"},
                "value": 1
            }
        ]
    }
}
```

### Viewing in Production (Dynatrace)
Because OpenTelemetry instruments these metrics natively, Dynatrace automatically recognizes them the moment they are ingested—no custom dashboard setup is strictly required.
1. Open your Dynatrace UI.
2. Navigate to **Observe and explore** → **Metrics** (or use the Data Explorer).
3. In the search bar, type the exact name of the metric you registered in your code (e.g., `hitl.escalations`, `errors.by_category`, or `store_locator.searches`).
4. You can then split (group by) the dimensions/attributes you attached in your code (like `escalation_type`) to create pie charts or timeseries graphs.

---

## 5. Setting Up Alerts (GCP Cloud Monitoring)

Because OpenTelemetry `Counters` are exported to GCP as `CUMULATIVE` metrics, they continuously increase over time. To alert when a specific event happens (like an SLA breach), you need to alert on the **delta** (the rate of change) rather than the absolute value.

### Example: Alerting on `hitl.sla_breaches`
If you want to trigger a PagerDuty or Slack alert the moment an SLA breach counter goes above zero in a 1-minute window, use the following steps in GCP.

#### Via the GCP Console (UI)
1. Go to **Monitoring** → **Alerting** → **Create Policy**.
2. Click **Select a metric** and search for `hitl.sla_breaches` (usually under `custom.googleapis.com/hitl.sla_breaches`).
3. Under **Transform data**, set:
   * **Rolling window:** `1 min`
   * **Rolling window function:** `delta`
4. Under **Configure condition**, set:
   * **Condition:** `is above`
   * **Threshold:** `0`

#### Via MQL (Monitoring Query Language)
If you are using Terraform or the Advanced MQL editor, you can paste this exact query:

```mql
fetch cloud_run_revision
| metric 'custom.googleapis.com/hitl.sla_breaches'
| align delta(1m)
| every 1m
| condition val() > 0
```

#### Alerting on Error Categories
You can also use this exact same pattern to alert on specific error spikes using the `errors.by_category` metric. 

For example, to alert if `rate_limit` errors exceed 5 per minute:
```mql
fetch cloud_run_revision
| metric 'custom.googleapis.com/errors.by_category'
| filter (metric.category == 'rate_limit')
| align delta(1m)
| every 1m
| condition val() > 5
```