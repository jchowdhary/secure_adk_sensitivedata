# Custom Metrics Usage Guide

This guide breaks down the 5 core metric domains available in the ADK Agents observability stack. Using the right metric class ensures your data is neatly organized in your dashboards (like GCP Monitoring or Dynatrace) and makes alerting much easier.

---

## 🛠️ Core Agent Decorators: Tracing & Retries

Before diving into specific metric categories, it is important to understand how we automatically track and protect the core agent invocations. We use two powerful decorators to wrap the `invoke` methods of our ADK Agents. This completely removes telemetry and retry boilerplate from your agent logic.

### 1. `@trace_agent_invocation(agent_name="...")`
*   **Why use it?** To gain instant observability into agent execution without polluting your clean agent logic with OpenTelemetry boilerplate.
*   **What happens?** When the agent is invoked, the decorator creates a new OpenTelemetry span named `{agent_name}.invoke`. It automatically extracts the agent's model name and configuration (like `disallow_transfer_to_peers`), injects them as span attributes, and safely captures any exceptions that bubble up to mark the trace as `ERROR`.

### 2. `@with_retry(max_retries=X)`
*   **Why use it?** To make agents highly resilient to transient network failures or LLM API rate limits without writing custom `while` loops and `asyncio.sleep` statements.
*   **What happens?** It intercepts exceptions and evaluates if they are safe to retry (e.g., `429 Rate Limit`, `503 Unavailable`, `Timeout`) using `SystemAndRuntimeMetrics`. If retryable, it calculates an exponential backoff time, adds a `retry_attempt` marker to your visual trace timeline, sleeps, and retries the function.

### 3. `@track_operation(operation_name="...")`
*   **Why use it?** While ADK Tools are tracked automatically, your agents likely rely on internal helper functions (like raw database queries or REST API fetches). You want to monitor the performance of these internal dependencies.
*   **What happens?** It wraps the function (supports both `async` and `sync`), records the start and end time, and automatically emits a `system.operation.latency` histogram metric along with a `success`/`failure` boolean flag if an exception occurs.

### 4. `@with_fallback(fallback_func, ...)`
*   **Why use it?** To ensure High Availability (HA) for critical paths by automatically routing to a backup function or a cheaper, faster model if the primary logic completely fails.
*   **What happens?** It catches any unhandled exception from the primary function, automatically emits a `system_event.fallback` metric/trace event logging the exact failure reason, and seamlessly executes your provided `fallback_func` with the original arguments.

**Usage Example (Inside your Agent classes):**
```python
from adk_web_api.telemetry import trace_agent_invocation
from adk_web_api.custom_metrics import with_retry
from google.adk.agents.invocation_context import InvocationContext

class SubAgent:
    # ... initialization ...

    @trace_agent_invocation(agent_name="sub_agent")
    @with_retry(max_retries=3)
    async def invoke(self, context: InvocationContext):
        """Invoke the sub agent. Telemetry and retries are handled automatically!"""
        return await self.agent.invoke(context)
```

---

**Usage Example (For Internal Helper Functions):**
Use `@track_operation` and `@with_fallback` on normal Python functions (like database queries or external REST API calls) that are utilized by your agents or tools.

```python
from adk_web_api.custom_metrics import track_operation, with_fallback

# 1. Define a fallback function with the exact same signature
async def fetch_cache_fallback(user_id: str):
    return {"status": "stale_cache_data", "user_id": user_id}

# 2. Decorate your primary, risky function
@track_operation(operation_name="fetch_user_profile")
@with_fallback(fallback_func=fetch_cache_fallback, fallback_type="database_read")
async def fetch_user_profile(user_id: str):
    # If the DB fails, it automatically emits the fallback metric and runs the cache fetch!
    return await db.query(f"SELECT * FROM users WHERE id = '{user_id}'")
```

---

## 1. System and Runtime Metrics
**Class:** `SystemAndRuntimeMetrics`

**What it tracks:** 
The physical health of your application and its dependencies. This includes API errors (rate limits, timeouts), retry attempts, fallback mechanisms (e.g., switching from Gemini Pro to Flash), and infrastructure tasks like loading secrets.

**Sample Use Case:** 
Your application relies on a third-party inventory API. During a holiday sale, the API starts rate-limiting your agents. You want to track these failures and monitor how often the system successfully retries.

**Usage Example:**
```python
from adk_web_api.custom_metrics import SystemAndRuntimeMetrics, ErrorCategory

try:
    inventory = check_inventory_api(item_id)
except Exception as e:
    # Record the error and automatically categorize it
    SystemAndRuntimeMetrics.record_error(
        category=ErrorCategory.RATE_LIMIT,
        error_code="429_TOO_MANY_REQUESTS",
        is_retryable=True,
        correlation_id=request.correlation_id
    )
    
    # Track the subsequent retry attempt
    SystemAndRuntimeMetrics.record_retry(
        attempt_number=1,
        category=ErrorCategory.RATE_LIMIT
    )
```

---

## 2. Governance and Risk Metrics
**Class:** `GovernanceAndRiskMetrics`

**What it tracks:** 
Security, compliance, and safety events. This includes PII (Personally Identifiable Information) masking, prompt injection attempts, and content safety blocks.

**Sample Use Case:** 
You are building a customer support agent. A user accidentally uploads their Social Security Number and Credit Card information into the chat. The DLP plugin masks it, and you need to track this compliance event for auditing purposes.

**Usage Example:**
```python
from adk_web_api.custom_metrics import GovernanceAndRiskMetrics

# Record that PII was detected and successfully masked
GovernanceAndRiskMetrics.record_policy_event(
    policy_type="pii_detected",
    action_taken="mask",
    trigger_reason="US_SOCIAL_SECURITY_NUMBER",
    severity="high",
    use_case="customer_support_chat"
)
```

---

## 3. Data and Output Quality Metrics
**Class:** `DataAndOutputQualityMetrics`

**What it tracks:** 
The semantic quality of the agent's work. This includes retrieval health (RAG cache hits/misses or empty search results), response groundedness (hallucination scores), and explicit user feedback (thumbs up/down).

**Sample Use Case:** 
Your agent searches a vector database to answer policy questions. You want to know how often the database returns empty results (Empty Retrieval Rate), and you want to track if users are accepting or rejecting the final answers.

**Usage Example:**
```python
from adk_web_api.custom_metrics import DataAndOutputQualityMetrics

# Track a retrieval event where the search turned up nothing
DataAndOutputQualityMetrics.record_retrieval(
    is_empty=True, 
    cache_hit=False, 
    tool_id="policy_vector_search"
)

# Track explicit user feedback when they click "Thumbs Down"
DataAndOutputQualityMetrics.record_user_feedback(
    outcome="rejected"
)
```

---

## 4. Agent Behavior Metrics
**Class:** `AgentBehaviorMetrics`

**What it tracks:** 
The internal reasoning and decision-making logic of your agents. This tracks routing decisions (who the orchestrator delegated to) and task evaluations (did the agent successfully complete its goal).

**Sample Use Case:** 
Your Orchestrator agent decides between routing to a "Billing Agent" or a "Tech Support Agent". You want to track the distribution of these routes and the AI's confidence score for each decision to detect if one sub-agent is being overloaded.

**Usage Example:**
```python
from adk_web_api.custom_metrics import AgentBehaviorMetrics

# Record the orchestrator's decision to delegate
AgentBehaviorMetrics.record_routing(
    decision_type="delegate",
    target_agent="billing_sub_agent",
    confidence_score=0.88
)

# Record a background evaluator's assessment of the final interaction
AgentBehaviorMetrics.record_evaluation(
    goal_completed=True,
    hallucination_detected=False,
    constraint_violated=False
)
```

---

## 5. HITL (Human-in-the-Loop) Operations Metrics
**Class:** `HITLOperationsMetrics`

**What it tracks:** 
Interactions between the AI and human agents. This includes escalations, time spent in the human review queue, and SLA (Service Level Agreement) breaches.

**Sample Use Case:** 
An AI attempts to process a refund but its confidence score is too low, so it creates a Zendesk ticket for a human. You want to track why it escalated, and later, how long it took the human to review it.

**Usage Example:**
```python
from adk_web_api.custom_metrics import HITLOperationsMetrics

# Record the AI escalating the task
HITLOperationsMetrics.record_escalation(
    escalation_type="low_confidence",
    reason="Refund amount exceeds auto-approval limit",
    agent_id="refund_agent"
)

# Later, record when the human finishes reviewing it
HITLOperationsMetrics.record_review_completed(
    reviewer_id="human_agent_42",
    duration_ms=45000,    # Human took 45 seconds to process
    queue_time_ms=120000, # Ticket sat in queue for 2 minutes
    decision="approved"
)
```

---

## 🚀 Adding Custom Attributes to Metrics

Every metric recording function in the system accepts an `attributes` dictionary. 

### What are Custom Attributes?
Attributes are key-value pairs attached to a metric. In your observability dashboard (GCP, Dynatrace, Datadog), attributes allow you to **slice, dice, filter, and group** your data.

### Why Use Them?
If you only emit `errors.by_category = 1`, you know an error happened. But if you emit `errors.by_category = 1` with attributes `{"region": "us-east", "customer_tier": "premium"}`, you can suddenly create a dashboard chart showing "Errors broken down by Region" or set up an alert specifically for "Errors affecting Premium Customers."

### Usage Example
Whenever you call a metric method, simply pass a dictionary to the `attributes` parameter:

```python
from adk_web_api.custom_metrics import DataAndOutputQualityMetrics

# Define the contextual data for this specific request
context_tags = {
    "tenant_id": "customer_123",
    "region": "us-central1",
    "user_tier": "enterprise",
    "app_version": "v2.1.0"
}

# Pass it into the metric
DataAndOutputQualityMetrics.record_user_feedback(
    outcome="accepted",
    attributes=context_tags
)
```

**Dashboard Result:**
In Google Cloud Monitoring, you can now write a query like: 
*"Show me the count of user_feedback where outcome = 'accepted' AND user_tier = 'enterprise'"*