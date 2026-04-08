# DLP Use-Case Filtering Solution

## Problem

The current DLP implementation supports filtering by:

- Scan stage
  - `scan_user_messages`
  - `scan_llm_requests`
  - `scan_llm_responses`
  - `scan_tool_calls`
  - `scan_tool_results`
- Agent scope
  - `agent_filter_mode`
  - `enabled_agents`
  - `disabled_agents`
- Info types
  - `EMAIL_ADDRESS`
  - `DATE_OF_BIRTH`
  - `PERSON_NAME`
  - etc.

This works well for infrastructure-level control, but it does not map cleanly to business use cases such as:

- `offers_and_discounts`
- `order_support`
- `account_recovery`
- `kyc_verification`
- `store_locator`

That makes policy management harder when the same agent handles multiple journeys.

## Goal

Add use-case-based DLP filtering so we can decide:

- which use cases require DLP
- which DLP stages apply for each use case
- which info types should be masked for each use case
- which agents and tools are allowed to participate in that use case

## Recommended Approach

Introduce a `use_case` value into the request context and evaluate DLP rules against it.

At a high level:

1. The API or orchestrator identifies the use case for the request.
2. That use case is attached to the ADK session, invocation context, or request metadata.
3. The DLP plugin reads the use case before each callback.
4. The plugin applies a matching DLP policy for that use case.

## Proposed Design

### 1. Add a DLP policy model

Create a new policy object in `dlp_config.py`.

Example structure:

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class UseCaseDLPPolicy:
    name: str
    enabled: bool = True
    scan_user_messages: bool = True
    scan_llm_requests: bool = True
    scan_llm_responses: bool = True
    scan_tool_calls: bool = True
    scan_tool_results: bool = True
    info_types: List[str] = field(default_factory=list)
    enabled_agents: List[str] = field(default_factory=list)
    enabled_tools: List[str] = field(default_factory=list)
```

This should not replace `DLPSettings`. It should sit on top of it.

`DLPSettings` stays the global/default configuration.

`UseCaseDLPPolicy` becomes the override layer for business flows.

### 2. Add use-case policies to DLP settings

Extend `DLPSettings` with:

```python
use_case_filter_enabled: bool = False
default_use_case: str = "default"
use_case_policies: Dict[str, UseCaseDLPPolicy] = field(default_factory=dict)
```

This allows you to define rules such as:

```python
settings.use_case_policies = {
    "offers_and_discounts": UseCaseDLPPolicy(
        name="offers_and_discounts",
        info_types=["PERSON_NAME", "DATE_OF_BIRTH", "EMAIL_ADDRESS", "PHONE_NUMBER"],
        enabled_agents=["orchestrator", "offer_agent"],
        enabled_tools=["get_customer_profile", "get_offer_catalog"]
    ),
    "store_locator": UseCaseDLPPolicy(
        name="store_locator",
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"],
        enabled_agents=["orchestrator", "store_agent"],
        enabled_tools=["search_stores"]
    ),
    "kyc_verification": UseCaseDLPPolicy(
        name="kyc_verification",
        info_types=[
            "PERSON_NAME",
            "DATE_OF_BIRTH",
            "US_SOCIAL_SECURITY_NUMBER",
            "PASSPORT_NUMBER",
            "US_DRIVER_LICENSE_NUMBER"
        ],
        enabled_agents=["orchestrator", "kyc_agent"],
        enabled_tools=["verify_identity", "check_watchlist"]
    ),
}
```

## How Use Case Should Be Passed

There are 3 practical options.

### Option A: Request body field

Add `use_case` to the FastAPI request model.

```python
class ChatRequest(BaseModel):
    message: str
    use_case: str = "default"
```

Then persist it into session state before calling the runner.

Best when:

- your frontend or caller already knows the journey
- the route is shared by many use cases

### Option B: Per-endpoint mapping

Map endpoint to use case.

Examples:

- `/invoke/offers` -> `offers_and_discounts`
- `/invoke/support` -> `order_support`
- `/invoke/kyc` -> `kyc_verification`

Best when:

- the route structure is already use-case based
- you want simpler API contracts

### Option C: Orchestrator classification

Let the orchestrator classify the request first and assign a use case.

Best when:

- requests are highly dynamic
- a single endpoint serves many journeys

Caution:

- this is more complex
- you may need a pre-routing stage before normal DLP policy selection

## Recommended Implementation Path

For your current codebase, Option A is the cleanest.

Why:

- minimal coupling
- predictable behavior
- easy to test
- simple to document

## Runtime Flow

With use-case filtering, the flow becomes:

1. FastAPI receives:

```json
{
  "message": "My date of birth is 26/11/1977 and my name is Jayant.",
  "use_case": "offers_and_discounts"
}
```

2. `main.py` stores `use_case="offers_and_discounts"` in session state or invocation metadata.

3. `DLPPlugin` resolves the active policy before each callback.

4. The plugin checks:

- is this use case enabled
- is this stage enabled for this use case
- is this agent allowed for this use case
- is this tool allowed for this use case

5. The plugin scans using the policy's `info_types`.

6. Masked content continues through the ADK flow.

## Plugin Changes Needed

### 1. Resolve active use case

Add a helper in `dlp_plugin.py`:

```python
def _get_use_case(self, callback_context: Any = None, invocation_context: Any = None) -> str:
    # Read from session state, invocation metadata, or a fallback default
    return self.settings.default_use_case
```

### 2. Resolve active policy

```python
def _get_policy_for_use_case(self, use_case: str) -> Optional[UseCaseDLPPolicy]:
    if not self.settings.use_case_filter_enabled:
        return None
    return self.settings.use_case_policies.get(use_case)
```

### 3. Stage-aware checks

For each callback, combine:

- global setting
- agent filter
- use-case policy

Example:

```python
policy = self._get_policy_for_use_case(use_case)
if policy and not policy.scan_llm_requests:
    return None
```

### 4. Tool-aware checks

Before scanning a tool call:

```python
if policy and policy.enabled_tools and tool.name not in policy.enabled_tools:
    return None
```

### 5. Use policy-specific info types

The cleanest pattern is to construct an effective DLP service for the current use case.

Example:

```python
effective_settings = copy.deepcopy(self.settings)
if policy and policy.info_types:
    effective_settings.info_types = policy.info_types
service = DLPService(effective_settings)
```

This avoids mutating shared plugin state mid-request.

## Example Policy for Your Use Case

For your request:

`My date of birth is 26/11/1977 and my name is Jayant. Can I get some offers and discounts because of my birth month?`

Recommended use case:

`offers_and_discounts`

Recommended policy:

```python
UseCaseDLPPolicy(
    name="offers_and_discounts",
    scan_user_messages=True,
    scan_llm_requests=True,
    scan_llm_responses=True,
    scan_tool_calls=True,
    scan_tool_results=True,
    info_types=[
        "PERSON_NAME",
        "DATE_OF_BIRTH",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD_NUMBER",
    ],
    enabled_agents=["orchestrator", "offer_agent"],
    enabled_tools=["get_customer_profile", "get_birthday_offers"]
)
```

This gives much better control than a global allowlist/blocklist.

## Why This Is Better Than Agent-Only Filtering

Agent-only filtering answers:

- which runtime component should be scanned

Use-case filtering answers:

- why are we scanning this request
- what kind of data matters for this business flow
- which tools and agents are relevant for this journey

That is much easier to manage over time.

## Suggested Precedence Rules

To avoid confusion, use this precedence order:

1. Global kill switch
   - If a global scan stage is disabled, skip scanning.
2. Use-case policy
   - If the active use case disables the stage, skip scanning.
3. Agent filter
   - If the agent is not allowed, skip scanning.
4. Tool filter
   - If the tool is not allowed, skip scanning.
5. Info type override
   - Use the use-case-specific list if present.
6. Fallback to global settings

This keeps behavior deterministic.

## Backward Compatibility

This design is backward compatible.

If `use_case_filter_enabled=False`, the system behaves exactly as it does today.

That means you can:

- introduce use-case policies gradually
- test one journey first
- keep existing agent filtering unchanged

## Testing Strategy

Add tests for:

1. Use case resolves correctly from request/session metadata
2. Correct policy is selected for `offers_and_discounts`
3. `DATE_OF_BIRTH` is masked for `offers_and_discounts`
4. Same field is not masked for a use case that does not include it
5. Tool filtering works per use case
6. Agent allowlist still works after use-case policy selection
7. Missing use case falls back to default behavior

## Recommended Next Step

Implement the smallest working slice:

1. Add `use_case` to `ChatRequest`
2. Add `UseCaseDLPPolicy`
3. Store one policy for `offers_and_discounts`
4. Apply it in:
   - `on_user_message_callback`
   - `before_model_callback`
   - `before_tool_callback`
5. Add 2 to 3 focused tests

That will prove the design without a large refactor.

## Summary

Your current DLP model is good for infrastructure filtering but not ideal for business-flow filtering.

The simplest scalable solution is:

- pass `use_case` from the API
- define per-use-case DLP policies
- resolve an effective DLP config at callback time

This will make DLP easier to manage for journeys like offers, support, KYC, and profile lookup.
