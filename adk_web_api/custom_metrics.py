"""
Custom Metrics Registry and Advanced Error Tracking

This module provides:
1. CustomMetricsRegistry - Register and emit user-defined metrics
2. Error categorization - Classify errors (rate limit, timeout, auth, etc.)
3. Retry/fallback tracking - Track retry attempts and fallback events
4. Secret Manager metrics - Track secret loading operations

Usage for Custom Metrics:
    from custom_metrics import CustomMetricsRegistry, MetricType
    
    # Register a custom metric
    registry = CustomMetricsRegistry()
    registry.register_counter(
        name="my_custom.counter",
        description="My custom counter",
        unit="count"
    )
    
    # Emit the metric
    registry.emit("my_custom.counter", value=1, attributes={"tag": "value"})
"""
import time
import threading
import asyncio
from functools import wraps
from typing import Optional, Dict, Any, Callable, List, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from opentelemetry import metrics, trace


# =============================================================================
# ERROR CATEGORIZATION
# =============================================================================

class ErrorCategory(Enum):
    """Categories of errors for classification."""
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    INVALID_REQUEST = "invalid_request"
    MODEL_NOT_FOUND = "model_not_found"
    CONTENT_FILTERED = "content_filtered"
    NETWORK_ERROR = "network_error"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"


@dataclass
class CategorizedError:
    """An error with its categorized type."""
    category: ErrorCategory
    original_error: Optional[Exception] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_retryable: bool = False
    suggested_backoff_ms: int = 0
    
    # Mapping of error codes/substrings to categories
    # Note: Order matters - more specific matches should come before general ones
    # Rate limit / quota errors (RESOURCE_EXHAUSTED is typically rate limiting in APIs)
    ERROR_MAPPINGS = {
        # Rate limit / quota errors
        "RATE_LIMIT": (ErrorCategory.RATE_LIMIT, True, 60000),
        "RESOURCE_EXHAUSTED": (ErrorCategory.RATE_LIMIT, True, 60000),
        "429": (ErrorCategory.RATE_LIMIT, True, 60000),
        "Too Many Requests": (ErrorCategory.RATE_LIMIT, True, 60000),
        "quota": (ErrorCategory.RATE_LIMIT, True, 60000),
        
        # Timeout errors
        "DEADLINE_EXCEEDED": (ErrorCategory.TIMEOUT, True, 5000),
        "TIMEOUT": (ErrorCategory.TIMEOUT, True, 5000),
        "timed out": (ErrorCategory.TIMEOUT, True, 5000),
        
        # Authentication errors (check these before timeout to avoid false matches)
        "UNAUTHENTICATED": (ErrorCategory.AUTHENTICATION, False, 0),
        "Invalid API key": (ErrorCategory.AUTHENTICATION, False, 0),
        "401": (ErrorCategory.AUTHENTICATION, False, 0),
        "Unauthorized": (ErrorCategory.AUTHENTICATION, False, 0),
        
        # Authorization errors
        "PERMISSION_DENIED": (ErrorCategory.AUTHORIZATION, False, 0),
        "403": (ErrorCategory.AUTHORIZATION, False, 0),
        "Forbidden": (ErrorCategory.AUTHORIZATION, False, 0),
        "access denied": (ErrorCategory.AUTHORIZATION, False, 0),
        
        # Resource errors (memory, etc.)
        "OUT_OF_MEMORY": (ErrorCategory.RESOURCE_EXHAUSTED, False, 0),
        "insufficient": (ErrorCategory.RESOURCE_EXHAUSTED, False, 0),
        
        # Invalid request
        "INVALID_ARGUMENT": (ErrorCategory.INVALID_REQUEST, False, 0),
        "BAD_REQUEST": (ErrorCategory.INVALID_REQUEST, False, 0),
        "400": (ErrorCategory.INVALID_REQUEST, False, 0),
        
        # Model not found
        "NOT_FOUND": (ErrorCategory.MODEL_NOT_FOUND, False, 0),
        "404": (ErrorCategory.MODEL_NOT_FOUND, False, 0),
        "model not found": (ErrorCategory.MODEL_NOT_FOUND, False, 0),
        "does not exist": (ErrorCategory.MODEL_NOT_FOUND, False, 0),
        
        # Content filtered
        "CONTENT_FILTERED": (ErrorCategory.CONTENT_FILTERED, False, 0),
        "SAFETY": (ErrorCategory.CONTENT_FILTERED, False, 0),
        "blocked": (ErrorCategory.CONTENT_FILTERED, False, 0),
        "prohibited": (ErrorCategory.CONTENT_FILTERED, False, 0),
        
        # Network errors
        "UNAVAILABLE": (ErrorCategory.NETWORK_ERROR, True, 2000),
        "NETWORK": (ErrorCategory.NETWORK_ERROR, True, 2000),
        "CONNECTION": (ErrorCategory.NETWORK_ERROR, True, 2000),
        "503": (ErrorCategory.NETWORK_ERROR, True, 2000),
        "connection refused": (ErrorCategory.NETWORK_ERROR, True, 2000),
        
        # Internal errors
        "INTERNAL": (ErrorCategory.INTERNAL_ERROR, True, 1000),
        "500": (ErrorCategory.INTERNAL_ERROR, True, 1000),
        "Internal Server Error": (ErrorCategory.INTERNAL_ERROR, True, 1000),
    }
    
    @classmethod
    def from_error(cls, error: Optional[Exception] = None, 
                   error_code: Optional[str] = None,
                   error_message: Optional[str] = None) -> "CategorizedError":
        """Categorize an error based on code and message."""
        # 1) Match explicit error_code first (highest priority).
        if error_code:
            error_code_upper = error_code.upper()
            for key, (category, retryable, backoff) in cls.ERROR_MAPPINGS.items():
                if key.upper() in error_code_upper:
                    return cls(
                        category=category,
                        original_error=error,
                        error_code=error_code,
                        error_message=error_message,
                        is_retryable=retryable,
                        suggested_backoff_ms=backoff,
                    )
        
        # 2) Then match message/exception text.
        combined = ""
        if error_message:
            combined += f" {error_message} "
        if error:
            combined += f" {str(error)} {type(error).__name__} "
        combined = combined.upper()
        
        for key, (category, retryable, backoff) in cls.ERROR_MAPPINGS.items():
            if key.upper() in combined:
                return cls(
                    category=category,
                    original_error=error,
                    error_code=error_code,
                    error_message=error_message,
                    is_retryable=retryable,
                    suggested_backoff_ms=backoff,
                )
        
        return cls(
            category=ErrorCategory.UNKNOWN,
            original_error=error,
            error_code=error_code,
            error_message=error_message,
            is_retryable=False,
            suggested_backoff_ms=0,
        )


# =============================================================================
# METRIC TYPES
# =============================================================================

class MetricType(Enum):
    """Types of metrics supported."""
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"  # Note: Gauge requires async callback in OTel


@dataclass
class MetricDefinition:
    """Definition of a custom metric."""
    name: str
    metric_type: MetricType
    description: str
    unit: str
    callback: Optional[Callable] = None  # For gauges


# =============================================================================
# CUSTOM METRICS REGISTRY
# =============================================================================

class CustomMetricsRegistry:
    """
    Registry for user-defined custom metrics.
    
    Users can register their own metrics that will be emitted alongside
    the standard LLM and tool metrics.
    
    Example:
        registry = CustomMetricsRegistry.get_instance()
        
        # Register a counter
        registry.register_counter(
            name="business.feature_x_usage",
            description="Number of times feature X was used",
            unit="count"
        )
        
        # Emit the metric
        registry.emit_counter("business.feature_x_usage", value=1, attributes={
            "user_tier": "premium"
        })
        
        # Register a histogram for timing
        registry.register_histogram(
            name="business.processing_time",
            description="Processing time for business logic",
            unit="ms"
        )
        
        registry.emit_histogram("business.processing_time", value=123.45)
    """
    
    _instance: Optional["CustomMetricsRegistry"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._metrics: Dict[str, MetricDefinition] = {}
                    cls._instance._counters: Dict[str, metrics.Counter] = {}
                    cls._instance._histograms: Dict[str, metrics.Histogram] = {}
                    cls._instance._initialized = False
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "CustomMetricsRegistry":
        """Get the singleton instance of the registry."""
        return cls()
    
    def initialize(self, meter: metrics.Meter) -> None:
        """Initialize all registered metrics with the OpenTelemetry meter."""
        self._meter = meter
        self._initialized = True
        
        # Create all registered metrics
        for name, definition in self._metrics.items():
            self._create_metric(definition)
    
    @classmethod
    def initialize_all(cls, meter: metrics.Meter) -> None:
        """Initialize all custom metric modules with an OpenTelemetry meter."""
        cls.get_instance().initialize(meter)
        SystemAndRuntimeMetrics.initialize(meter)
        GovernanceAndRiskMetrics.initialize(meter)
        DataAndOutputQualityMetrics.initialize(meter)
        AgentBehaviorMetrics.initialize(meter)
        HITLOperationsMetrics.initialize(meter)

    def _create_metric(self, definition: MetricDefinition) -> None:
        """Create an OpenTelemetry metric from a definition."""
        if definition.metric_type == MetricType.COUNTER:
            self._counters[definition.name] = self._meter.create_counter(
                name=definition.name,
                description=definition.description,
                unit=definition.unit,
            )
        elif definition.metric_type == MetricType.HISTOGRAM:
            self._histograms[definition.name] = self._meter.create_histogram(
                name=definition.name,
                description=definition.description,
                unit=definition.unit,
            )
        # Note: Gauges in OTel require observable callbacks
    
    def register_counter(self, name: str, description: str, unit: str = "count") -> None:
        """Register a counter metric."""
        definition = MetricDefinition(
            name=name,
            metric_type=MetricType.COUNTER,
            description=description,
            unit=unit,
        )
        self._metrics[name] = definition
        
        if self._initialized:
            self._create_metric(definition)
    
    def register_histogram(self, name: str, description: str, unit: str = "ms") -> None:
        """Register a histogram metric."""
        definition = MetricDefinition(
            name=name,
            metric_type=MetricType.HISTOGRAM,
            description=description,
            unit=unit,
        )
        self._metrics[name] = definition
        
        if self._initialized:
            self._create_metric(definition)
    
    def emit_counter(self, name: str, value: int = 1, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Emit a counter metric."""
        if name not in self._counters:
            raise ValueError(f"Counter '{name}' not registered")
        
        self._counters[name].add(value, attributes or {})
    
    def emit_histogram(self, name: str, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Emit a histogram metric."""
        if name not in self._histograms:
            raise ValueError(f"Histogram '{name}' not registered")
        
        self._histograms[name].record(value, attributes or {})
    
    def is_registered(self, name: str) -> bool:
        """Check if a metric is registered."""
        return name in self._metrics


# =============================================================================
# RETRY/FALLBACK TRACKING
# =============================================================================

@dataclass
class RetryEvent:
    """Information about a retry attempt."""
    attempt_number: int
    max_attempts: int
    backoff_ms: float
    error: Optional[Exception] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_category: Optional[ErrorCategory] = None
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackEvent:
    """Information about a fallback to alternative model/config."""
    fallback_type: str  # "model", "region", "provider"
    original_value: str
    fallback_value: str
    reason: str
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: Dict[str, Any] = field(default_factory=dict)


class RetryTracker:
    """Track retry attempts and emit metrics."""
    
    _retry_counts: Dict[str, int] = {}  # correlation_id -> attempt count
    
    @classmethod
    def record_retry_attempt(
        cls,
        correlation_id: str,
        error: Optional[Exception] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        max_attempts: int = 3,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> RetryEvent:
        """Record a retry attempt and return the event."""
        # Increment retry count
        current_attempt = cls._retry_counts.get(correlation_id, 0) + 1
        cls._retry_counts[correlation_id] = current_attempt
        
        # Categorize the error
        categorized = CategorizedError.from_error(error, error_code, error_message)
        
        # Calculate backoff with exponential backoff
        base_backoff = categorized.suggested_backoff_ms
        backoff_ms = base_backoff * (2 ** (current_attempt - 1))
        
        event = RetryEvent(
            attempt_number=current_attempt,
            max_attempts=max_attempts,
            backoff_ms=backoff_ms,
            error=error,
            error_code=error_code,
            error_message=error_message,
            error_category=categorized.category,
            correlation_id=correlation_id,
            attributes=attributes or {},
        )
        
        
        return event
    
    @classmethod
    def reset(cls, correlation_id: str) -> None:
        """Reset retry count for a correlation ID."""
        if correlation_id in cls._retry_counts:
            del cls._retry_counts[correlation_id]
            
            
def with_retry(max_retries: int = 3):
    """Decorator to automatically retry an agent invocation with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, context, *args, **kwargs):
            correlation_id = getattr(context, "invocation_id", "unknown_invocation")
            if correlation_id != "unknown_invocation":
                correlation_id = f"corr-{correlation_id}"
                
            for attempt in range(1, max_retries + 1):
                try:
                    result = await func(self, context, *args, **kwargs)
                    if max_retries > 1:
                        RetryTracker.reset(correlation_id)
                    return result
                except Exception as e:
                    categorized = SystemAndRuntimeMetrics.record_and_categorize(
                        error=e, correlation_id=correlation_id
                    )
                    
                    if categorized.is_retryable and attempt < max_retries:
                        retry_event = RetryTracker.record_retry_attempt(
                            correlation_id=correlation_id, error=e, max_attempts=max_retries
                        )
                        # Add visual trace event if OTel is capturing
                        span = trace.get_current_span()
                        if span and span.is_recording():
                            span.add_event("retry_attempt", {
                                "attempt": attempt,
                                "max_attempts": max_retries,
                                "backoff_ms": retry_event.backoff_ms,
                                "error.message": str(e)
                            })
                        await asyncio.sleep(retry_event.backoff_ms / 1000.0)
                        continue
                    raise
        return wrapper
    return decorator


def track_operation(operation_name: str):
    """Decorator to measure execution time and success rate of internal helper functions."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                return await func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                SystemAndRuntimeMetrics.record_operation_latency(operation_name, latency_ms, success)
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                return func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                SystemAndRuntimeMetrics.record_operation_latency(operation_name, latency_ms, success)
                
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def with_fallback(fallback_func: Callable, fallback_type: str = "function", reason: str = "primary_failed"):
    """Decorator to automatically route to a backup function on failure and emit metrics."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                SystemAndRuntimeMetrics.record_fallback(fallback_type, f"{reason}: {str(e)}")
                return await fallback_func(*args, **kwargs) if asyncio.iscoroutinefunction(fallback_func) else fallback_func(*args, **kwargs)
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                SystemAndRuntimeMetrics.record_fallback(fallback_type, f"{reason}: {str(e)}")
                return fallback_func(*args, **kwargs)
                
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


class FallbackTracker:
    """Track fallback events and emit metrics."""
    
    @classmethod
    def record_fallback(
        cls,
        fallback_type: str,
        original_value: str,
        fallback_value: str,
        reason: str,
        correlation_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> FallbackEvent:
        """Record a fallback event."""
        event = FallbackEvent(
            fallback_type=fallback_type,
            original_value=original_value,
            fallback_value=fallback_value,
            reason=reason,
            correlation_id=correlation_id,
            attributes=attributes or {},
        )
        
        
        return event


# =============================================================================
# BASE DOMAIN METRICS (Reduces Boilerplate)
# =============================================================================

class BaseMetricGroup:
    """Base class to reduce boilerplate for metric & trace event emission."""
    _initialized = False

    @classmethod
    def _emit_counter(cls, counter: Optional[metrics.Counter], event_name: str, attrs: dict):
        if not cls._initialized or not counter: return
        counter.add(1, attrs)
        span = trace.get_current_span()
        if span and span.is_recording() and event_name:
            span.add_event(event_name, attrs)

    @classmethod
    def _emit_histogram(cls, histogram: Optional[metrics.Histogram], value: float, event_name: Optional[str], attrs: dict):
        if not cls._initialized or not histogram: return
        histogram.record(value, attrs)
        span = trace.get_current_span()
        if span and span.is_recording() and event_name:
            span.add_event(event_name, {"value": value, **attrs})


# =============================================================================
# 1. SYSTEM AND RUNTIME METRICS
# =============================================================================

class SystemAndRuntimeMetrics(BaseMetricGroup):
    """System and Runtime: Covers Errors, Retries, Fallbacks, and Secret Loads."""
    
    _secret_load_counter: Optional[metrics.Counter] = None
    _secret_latency_hist: Optional[metrics.Histogram] = None
    _secret_error_counter: Optional[metrics.Counter] = None
    _error_counter: Optional[metrics.Counter] = None
    _operation_latency_hist: Optional[metrics.Histogram] = None
    _retry_counter: Optional[metrics.Counter] = None
    _fallback_counter: Optional[metrics.Counter] = None
    
    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        cls._secret_load_counter = meter.create_counter("secret_manager.loads", unit="loads")
        cls._secret_latency_hist = meter.create_histogram("secret_manager.latency", unit="ms")
        cls._secret_error_counter = meter.create_counter("secret_manager.errors", unit="errors")
        cls._operation_latency_hist = meter.create_histogram("system.operation.latency", unit="ms")
        cls._error_counter = meter.create_counter("errors.by_category", unit="errors")
        cls._retry_counter = meter.create_counter("retries.total", unit="retries")
        cls._fallback_counter = meter.create_counter("fallbacks.total", unit="fallbacks")
        cls._initialized = True
    
    @classmethod
    def record_secret_load(cls, secret_id: str, latency_ms: float, success: bool = True, error: Optional[str] = None, attributes=None):
        attrs = {"secret_id": secret_id, "success": success}
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._secret_load_counter, "secret_event.load", attrs)
        cls._emit_histogram(cls._secret_latency_hist, latency_ms, None, attrs)
        if not success:
            cls._emit_counter(cls._secret_error_counter, "secret_event.error", {**attrs, "error": error or "unknown"})

    @classmethod
    def record_operation_latency(cls, operation_name: str, latency_ms: float, success: bool = True, attributes=None):
        attrs = {"operation_name": operation_name, "success": success}
        if attributes: attrs.update(attributes)
        cls._emit_histogram(cls._operation_latency_hist, latency_ms, "system_event.operation", attrs)

    @classmethod
    def record_error(cls, category: ErrorCategory, error_code=None, correlation_id=None, is_retryable=False, attributes=None):
        attrs = {"category": category.value, "is_retryable": is_retryable}
        if error_code: attrs["error_code"] = error_code
        if correlation_id: attrs["correlation_id"] = correlation_id
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._error_counter, "system_event.error", attrs)
    
    @classmethod
    def record_retry(cls, attempt_number: int, category: ErrorCategory, correlation_id=None, attributes=None):
        attrs = {"attempt": attempt_number, "category": category.value}
        if correlation_id: attrs["correlation_id"] = correlation_id
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._retry_counter, "system_event.retry", attrs)
    
    @classmethod
    def record_fallback(cls, fallback_type: str, reason: str, correlation_id=None, attributes=None):
        attrs = {"fallback_type": fallback_type, "reason": reason}
        if correlation_id: attrs["correlation_id"] = correlation_id
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._fallback_counter, "system_event.fallback", attrs)
        
    @classmethod
    def record_and_categorize(cls, error=None, error_code=None, error_message=None, correlation_id=None, attributes=None) -> CategorizedError:
        categorized = CategorizedError.from_error(error, error_code, error_message)
        cls.record_error(
            category=categorized.category,
            error_code=error_code,
            correlation_id=correlation_id,
            is_retryable=categorized.is_retryable,
            attributes=attributes
        )
        return categorized


# =============================================================================
# 2. GOVERNANCE AND RISK METRICS
# =============================================================================

class GovernanceAndRiskMetrics(BaseMetricGroup):
    """Governance and Risk: Covers Policy violations, Safety blocks, Prompt injections, and PII masking."""

    _policy_counter: Optional[metrics.Counter] = None

    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        cls._policy_counter = meter.create_counter("governance.policy_events", unit="events")
        cls._initialized = True

    @classmethod
    def record_policy_event(cls, policy_type: str, action_taken: str, trigger_reason: str, severity: str = "medium", use_case: Optional[str] = None, attributes=None):
        """Record policy violations like pii_detected, prompt_injection, safety_violation."""
        attrs = {"policy_type": policy_type, "action_taken": action_taken, "trigger_reason": trigger_reason, "severity": severity}
        if use_case: attrs["use_case"] = use_case
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._policy_counter, f"policy_event.{policy_type}", attrs)


# =============================================================================
# 3. DATA AND OUTPUT QUALITY METRICS
# =============================================================================

class DataAndOutputQualityMetrics(BaseMetricGroup):
    """Data and Output Quality: Covers Retrieval hit/empty rates, Groundedness, and User feedback."""

    _retrieval_counter: Optional[metrics.Counter] = None
    _groundedness_hist: Optional[metrics.Histogram] = None
    _feedback_counter: Optional[metrics.Counter] = None

    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        cls._retrieval_counter = meter.create_counter("quality.retrieval_events", unit="events")
        cls._groundedness_hist = meter.create_histogram("quality.groundedness", unit="score")
        cls._feedback_counter = meter.create_counter("quality.user_feedback", unit="events")
        cls._initialized = True

    @classmethod
    def record_retrieval(cls, is_empty: bool, cache_hit: bool, tool_id: Optional[str] = None, attributes=None):
        attrs = {"is_empty": is_empty, "cache_hit": cache_hit}
        if tool_id: attrs["tool_id"] = tool_id
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._retrieval_counter, "quality_event.retrieval", attrs)

    @classmethod
    def record_groundedness(cls, score: float, use_case: Optional[str] = None, subagent_id: Optional[str] = None, attributes=None):
        attrs = {}
        if use_case: attrs["use_case"] = use_case
        if subagent_id: attrs["subagent_id"] = subagent_id
        if attributes: attrs.update(attributes)
        cls._emit_histogram(cls._groundedness_hist, score, "quality_event.groundedness", attrs)

    @classmethod
    def record_user_feedback(cls, outcome: str, attributes=None):
        """Record user feedback (e.g., 'accepted', 'rephrased', 'corrected')."""
        attrs = {"outcome": outcome}
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._feedback_counter, "quality_event.user_feedback", attrs)


# =============================================================================
# 4. AGENT BEHAVIOR METRICS
# =============================================================================

class AgentBehaviorMetrics(BaseMetricGroup):
    """Agent Behavior: Covers Routing decisions, Goal completion accuracy, and Hallucinations."""

    _routing_counter: Optional[metrics.Counter] = None
    _routing_confidence: Optional[metrics.Histogram] = None
    _evaluation_counter: Optional[metrics.Counter] = None

    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        cls._routing_counter = meter.create_counter("behavior.routing_decisions", unit="events")
        cls._routing_confidence = meter.create_histogram("behavior.routing_confidence", unit="score")
        cls._evaluation_counter = meter.create_counter("behavior.evaluations", unit="events")
        cls._initialized = True

    @classmethod
    def record_routing(cls, decision_type: str, confidence_score: float, target_agent: Optional[str] = None, attributes=None):
        """Record agent routing choices (e.g., 'route', 'respond', 'escalate')."""
        attrs = {"decision_type": decision_type}
        if target_agent: attrs["target_agent"] = target_agent
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._routing_counter, "behavior_event.routing", attrs)
        if confidence_score > 0:
            cls._emit_histogram(cls._routing_confidence, confidence_score, None, attrs)

    @classmethod
    def record_evaluation(cls, goal_completed: bool, hallucination_detected: bool, constraint_violated: bool, attributes=None):
        attrs = {"goal_completed": goal_completed, "hallucination_detected": hallucination_detected, "constraint_violated": constraint_violated}
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._evaluation_counter, "behavior_event.evaluation", attrs)


# =============================================================================
# 5. HITL OPERATIONS METRICS
# =============================================================================

class HITLOperationsMetrics(BaseMetricGroup):
    """HITL Operations: Covers human escalations, Queue SLAs, Review times, and Handoffs."""

    _escalation_counter: Optional[metrics.Counter] = None
    _review_duration_hist: Optional[metrics.Histogram] = None
    _queue_time_hist: Optional[metrics.Histogram] = None
    _sla_breach_counter: Optional[metrics.Counter] = None
    _handoff_counter: Optional[metrics.Counter] = None

    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        cls._escalation_counter = meter.create_counter("hitl.escalations", unit="events")
        cls._review_duration_hist = meter.create_histogram("hitl.review_duration", unit="ms")
        cls._queue_time_hist = meter.create_histogram("hitl.queue_time", unit="ms")
        cls._sla_breach_counter = meter.create_counter("hitl.sla_breaches", unit="events")
        cls._handoff_counter = meter.create_counter("hitl.handoffs", unit="events")
        cls._initialized = True

    @classmethod
    def record_escalation(cls, escalation_type: str, reason: str, agent_id: Optional[str] = None, attributes=None):
        attrs = {"escalation_type": escalation_type, "escalation_reason": reason}
        if agent_id: attrs["escalating_agent_id"] = agent_id
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._escalation_counter, "hitl_event.escalation", attrs)

    @classmethod
    def record_review_completed(cls, reviewer_id: str, duration_ms: float, queue_time_ms: float, decision: str, escalation_type: Optional[str] = None, attributes=None):
        attrs = {"reviewer_id": reviewer_id, "reviewer_decision": decision}
        if escalation_type: attrs["escalation_type"] = escalation_type
        if attributes: attrs.update(attributes)
        cls._emit_histogram(cls._review_duration_hist, duration_ms, "hitl_event.review_completed", attrs)
        cls._emit_histogram(cls._queue_time_hist, queue_time_ms, None, attrs)

    @classmethod
    def record_sla_breach(cls, escalation_type: str, attributes=None):
        attrs = {"escalation_type": escalation_type}
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._sla_breach_counter, "hitl_event.sla_breach", attrs)

    @classmethod
    def record_handoff(cls, destination: str, reason: str, attributes=None):
        attrs = {"destination": destination, "reason": reason}
        if attributes: attrs.update(attributes)
        cls._emit_counter(cls._handoff_counter, "hitl_event.handoff", attrs)
