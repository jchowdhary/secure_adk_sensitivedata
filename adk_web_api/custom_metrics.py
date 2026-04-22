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

Usage for Hooks:
    from custom_metrics import MetricsHooks
    
    # Register a callback to be called on LLM events
    MetricsHooks.on_llm_call_start(callback=my_callback)
    MetricsHooks.on_llm_call_end(callback=my_callback)
    MetricsHooks.on_error(callback=my_error_callback)
"""
import time
import threading
from typing import Optional, Dict, Any, Callable, List, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from opentelemetry import metrics


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
        ErrorMetrics.initialize(meter)
        SecretManagerMetrics.initialize(meter)
        GovernanceAndQualityMetrics.initialize(meter)
        HITLMetrics.initialize(meter)

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
# METRICS HOOKS - Callbacks for Custom Logic
# =============================================================================

class MetricsHooks:
    """
    Hook system for custom callbacks on telemetry events.
    
    Users can register callbacks that fire on various events:
    - LLM call start/end
    - Tool call start/end
    - Error events
    - Retry events
    
    Example:
        def my_llm_callback(event_type, data):
            print(f"LLM event: {event_type}, model: {data.get('model')}")
            # Do custom logic, update external systems, etc.
        
        MetricsHooks.on_llm_call_end(my_llm_callback)
    """
    
    _llm_start_callbacks: List[Callable] = []
    _llm_end_callbacks: List[Callable] = []
    _tool_start_callbacks: List[Callable] = []
    _tool_end_callbacks: List[Callable] = []
    _error_callbacks: List[Callable] = []
    _retry_callbacks: List[Callable] = []
    _fallback_callbacks: List[Callable] = []
    
    @classmethod
    def on_llm_call_start(cls, callback: Callable) -> None:
        """Register a callback for LLM call start events.
        
        Callback signature: callback(event_type: str, data: Dict[str, Any])
        Data includes: call_id, model, agent_name, call_type, correlation_id, etc.
        """
        cls._llm_start_callbacks.append(callback)
    
    @classmethod
    def on_llm_call_end(cls, callback: Callable) -> None:
        """Register a callback for LLM call end events.
        
        Data includes: call_id, model, latency_ms, input_tokens, output_tokens,
        success, error_code, error_message, cost_usd, etc.
        """
        cls._llm_end_callbacks.append(callback)
    
    @classmethod
    def on_tool_call_start(cls, callback: Callable) -> None:
        """Register a callback for tool call start events."""
        cls._tool_start_callbacks.append(callback)
    
    @classmethod
    def on_tool_call_end(cls, callback: Callable) -> None:
        """Register a callback for tool call end events."""
        cls._tool_end_callbacks.append(callback)
    
    @classmethod
    def on_error(cls, callback: Callable) -> None:
        """Register a callback for error events.
        
        Data includes: error_category, error_code, error_message, is_retryable,
        suggested_backoff_ms, correlation_id, etc.
        """
        cls._error_callbacks.append(callback)
    
    @classmethod
    def on_retry(cls, callback: Callable) -> None:
        """Register a callback for retry events.
        
        Data includes: attempt_number, max_attempts, backoff_ms, error, etc.
        """
        cls._retry_callbacks.append(callback)
    
    @classmethod
    def on_fallback(cls, callback: Callable) -> None:
        """Register a callback for fallback events.
        
        Data includes: fallback_type, original_model, fallback_model, reason, etc.
        """
        cls._fallback_callbacks.append(callback)
    
    @classmethod
    def trigger(cls, callbacks: List[Callable], event_type: str, data: Dict[str, Any]) -> None:
        """Trigger all callbacks for an event type."""
        for callback in callbacks:
            try:
                callback(event_type, data)
            except Exception as e:
                # Don't let callback errors break the main flow
                import logging
                logging.warning(f"Metrics callback error: {e}")
    
    @classmethod
    def trigger_llm_start(cls, data: Dict[str, Any]) -> None:
        """Trigger LLM start callbacks."""
        cls.trigger(cls._llm_start_callbacks, "llm_call_start", data)
    
    @classmethod
    def trigger_llm_end(cls, data: Dict[str, Any]) -> None:
        """Trigger LLM end callbacks."""
        cls.trigger(cls._llm_end_callbacks, "llm_call_end", data)
    
    @classmethod
    def trigger_tool_start(cls, data: Dict[str, Any]) -> None:
        """Trigger tool start callbacks."""
        cls.trigger(cls._tool_start_callbacks, "tool_call_start", data)
    
    @classmethod
    def trigger_tool_end(cls, data: Dict[str, Any]) -> None:
        """Trigger tool end callbacks."""
        cls.trigger(cls._tool_end_callbacks, "tool_call_end", data)
    
    @classmethod
    def trigger_error(cls, data: Dict[str, Any]) -> None:
        """Trigger error callbacks."""
        cls.trigger(cls._error_callbacks, "error", data)
    
    @classmethod
    def trigger_retry(cls, data: Dict[str, Any]) -> None:
        """Trigger retry callbacks."""
        cls.trigger(cls._retry_callbacks, "retry", data)
    
    @classmethod
    def trigger_fallback(cls, data: Dict[str, Any]) -> None:
        """Trigger fallback callbacks."""
        cls.trigger(cls._fallback_callbacks, "fallback", data)


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
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FallbackEvent:
    """Information about a fallback to alternative model/config."""
    fallback_type: str  # "model", "region", "provider"
    original_value: str
    fallback_value: str
    reason: str
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


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
        )
        
        # Trigger hooks
        MetricsHooks.trigger_retry({
            "attempt_number": current_attempt,
            "max_attempts": max_attempts,
            "backoff_ms": backoff_ms,
            "error_code": error_code,
            "error_message": error_message,
            "error_category": categorized.category.value,
            "is_retryable": categorized.is_retryable,
            "correlation_id": correlation_id,
        })
        
        return event
    
    @classmethod
    def reset(cls, correlation_id: str) -> None:
        """Reset retry count for a correlation ID."""
        if correlation_id in cls._retry_counts:
            del cls._retry_counts[correlation_id]


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
    ) -> FallbackEvent:
        """Record a fallback event."""
        event = FallbackEvent(
            fallback_type=fallback_type,
            original_value=original_value,
            fallback_value=fallback_value,
            reason=reason,
            correlation_id=correlation_id,
        )
        
        # Trigger hooks
        MetricsHooks.trigger_fallback({
            "fallback_type": fallback_type,
            "original_value": original_value,
            "fallback_value": fallback_value,
            "reason": reason,
            "correlation_id": correlation_id,
        })
        
        return event


# =============================================================================
# SECRET MANAGER METRICS
# =============================================================================

class SecretManagerMetrics:
    """Metrics for Secret Manager operations."""
    
    _initialized = False
    _secret_load_counter: Optional[metrics.Counter] = None
    _secret_latency_hist: Optional[metrics.Histogram] = None
    _secret_error_counter: Optional[metrics.Counter] = None
    
    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        """Initialize Secret Manager metrics."""
        cls._secret_load_counter = meter.create_counter(
            "secret_manager.loads",
            unit="loads",
            description="Number of secrets loaded from Secret Manager",
        )
        cls._secret_latency_hist = meter.create_histogram(
            "secret_manager.latency",
            unit="ms",
            description="Latency of Secret Manager operations",
        )
        cls._secret_error_counter = meter.create_counter(
            "secret_manager.errors",
            unit="errors",
            description="Number of Secret Manager errors",
        )
        cls._initialized = True
    
    @classmethod
    def record_load(
        cls,
        secret_id: str,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Record a secret load operation."""
        if not cls._initialized:
            return
        
        attrs = {
            "secret_id": secret_id,
            "success": success,
        }
        
        cls._secret_load_counter.add(1, attrs)
        cls._secret_latency_hist.record(latency_ms, attrs)
        
        if not success:
            error_attrs = {**attrs, "error": error or "unknown"}
            cls._secret_error_counter.add(1, error_attrs)


# =============================================================================
# BUILT-IN ERROR CATEGORY METRICS
# =============================================================================

class ErrorMetrics:
    """Pre-defined metrics for error categorization."""
    
    _initialized = False
    _error_counter: Optional[metrics.Counter] = None
    _retry_counter: Optional[metrics.Counter] = None
    _fallback_counter: Optional[metrics.Counter] = None
    
    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        """Initialize error metrics."""
        cls._error_counter = meter.create_counter(
            "errors.by_category",
            unit="errors",
            description="Errors categorized by type",
        )
        cls._retry_counter = meter.create_counter(
            "retries.total",
            unit="retries",
            description="Total number of retry attempts",
        )
        cls._fallback_counter = meter.create_counter(
            "fallbacks.total",
            unit="fallbacks",
            description="Total number of fallback events",
        )
        cls._initialized = True
    
    @classmethod
    def record_error(
        cls,
        category: ErrorCategory,
        error_code: Optional[str] = None,
        correlation_id: Optional[str] = None,
        is_retryable: bool = False,
    ) -> None:
        """Record a categorized error."""
        if not cls._initialized:
            return
        
        attrs = {
            "category": category.value,
            "is_retryable": is_retryable,
        }
        if error_code:
            attrs["error_code"] = error_code
        if correlation_id:
            attrs["correlation_id"] = correlation_id
        
        cls._error_counter.add(1, attrs)
    
    @classmethod
    def record_retry(
        cls,
        attempt_number: int,
        category: ErrorCategory,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Record a retry attempt."""
        if not cls._initialized:
            return
        
        attrs = {
            "attempt": attempt_number,
            "category": category.value,
        }
        if correlation_id:
            attrs["correlation_id"] = correlation_id
        
        cls._retry_counter.add(1, attrs)
    
    @classmethod
    def record_fallback(
        cls,
        fallback_type: str,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Record a fallback event."""
        if not cls._initialized:
            return
        
        attrs = {
            "fallback_type": fallback_type,
            "reason": reason,
        }
        if correlation_id:
            attrs["correlation_id"] = correlation_id
        
        cls._fallback_counter.add(1, attrs)
        
    @classmethod
    def record_and_categorize(
        cls,
        error: Optional[Exception] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> CategorizedError:
        """Categorize an error and record it to metrics."""
        categorized = CategorizedError.from_error(error, error_code, error_message)
        
        # Record to error metrics
        cls.record_error(
            category=categorized.category,
            error_code=error_code,
            correlation_id=correlation_id,
            is_retryable=categorized.is_retryable,
        )
        
        # Trigger error hooks
        MetricsHooks.trigger_error({
            "category": categorized.category.value,
            "error_code": error_code,
            "error_message": error_message,
            "is_retryable": categorized.is_retryable,
            "suggested_backoff_ms": categorized.suggested_backoff_ms,
            "correlation_id": correlation_id,
        })
        
        return categorized


# =============================================================================
# GOVERNANCE, RISK, AND QUALITY METRICS
# =============================================================================

class GovernanceAndQualityMetrics:
    """Metrics for Data Quality, Governance, Safety, and Agent Behavior."""
    
    _initialized = False
    _pii_counter: Optional[metrics.Counter] = None
    _safety_counter: Optional[metrics.Counter] = None
    _cache_counter: Optional[metrics.Counter] = None
    _groundedness_hist: Optional[metrics.Histogram] = None
    
    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        """Initialize governance and quality metrics."""
        cls._pii_counter = meter.create_counter(
            "governance.pii_detected",
            unit="events",
            description="Number of PII detection/masking events",
        )
        cls._safety_counter = meter.create_counter(
            "governance.safety_triggered",
            unit="events",
            description="Number of LLM safety blocks or policy violations",
        )
        cls._cache_counter = meter.create_counter(
            "quality.cache_events",
            unit="events",
            description="Cache hit or miss events for retrieval and tools",
        )
        cls._groundedness_hist = meter.create_histogram(
            "quality.groundedness_score",
            unit="score",
            description="Semantic groundedness/relevance score of the agent output",
        )
        cls._initialized = True

    @classmethod
    def record_pii_detected(cls, info_type: str, action_taken: str, use_case: Optional[str] = None) -> None:
        """Record a PII/DLP detection event."""
        if not cls._initialized: return
        attrs = {"info_type": info_type, "action_taken": action_taken}
        if use_case: attrs["use_case"] = use_case
        cls._pii_counter.add(1, attrs)

    @classmethod
    def record_safety_trigger(cls, trigger_reason: str, channel: Optional[str] = None) -> None:
        """Record a safety block or content filtering event."""
        if not cls._initialized: return
        attrs = {"trigger_reason": trigger_reason}
        if channel: attrs["channel"] = channel
        cls._safety_counter.add(1, attrs)

    @classmethod
    def record_cache_event(cls, is_hit: bool, cache_type: str, tool_id: Optional[str] = None) -> None:
        """Record a cache hit or miss."""
        if not cls._initialized: return
        attrs = {
            "status": "hit" if is_hit else "miss",
            "cache_type": cache_type
        }
        if tool_id: attrs["tool_id"] = tool_id
        cls._cache_counter.add(1, attrs)

    @classmethod
    def record_groundedness(cls, score: float, use_case: Optional[str] = None, subagent_id: Optional[str] = None) -> None:
        """Record the quality/groundedness score of an agent response."""
        if not cls._initialized: return
        attrs = {}
        if use_case: attrs["use_case"] = use_case
        if subagent_id: attrs["subagent_id"] = subagent_id
        cls._groundedness_hist.record(score, attrs)


# =============================================================================
# HUMAN-IN-THE-LOOP (HITL) METRICS
# =============================================================================

class HITLMetrics:
    """Metrics for Human-in-the-Loop (HITL) escalations and reviews."""
    
    _initialized = False
    _escalation_counter: Optional[metrics.Counter] = None
    _review_duration_hist: Optional[metrics.Histogram] = None
    _queue_time_hist: Optional[metrics.Histogram] = None
    _sla_breach_counter: Optional[metrics.Counter] = None
    
    @classmethod
    def initialize(cls, meter: metrics.Meter) -> None:
        """Initialize HITL metrics."""
        cls._escalation_counter = meter.create_counter(
            "hitl.escalations", unit="events", description="Number of escalations to a human reviewer"
        )
        cls._review_duration_hist = meter.create_histogram(
            "hitl.review_duration", unit="ms", description="Time taken by human to review the task"
        )
        cls._queue_time_hist = meter.create_histogram(
            "hitl.queue_time", unit="ms", description="Time spent waiting in the queue for a human"
        )
        cls._sla_breach_counter = meter.create_counter(
            "hitl.sla_breaches", unit="events", description="Number of HITL SLA queue breaches"
        )
        cls._initialized = True

    @classmethod
    def record_escalation(cls, escalation_type: str, reason: str, agent_id: Optional[str] = None) -> None:
        """Record when a task is escalated to a human."""
        if not cls._initialized: return
        attrs = {"escalation_type": escalation_type, "escalation_reason": reason}
        if agent_id: attrs["escalating_agent_id"] = agent_id
        cls._escalation_counter.add(1, attrs)

    @classmethod
    def record_review_completed(cls, reviewer_id: str, duration_ms: float, queue_time_ms: float, decision: str, escalation_type: Optional[str] = None) -> None:
        """Record the completion of a human review, including duration and queue wait time."""
        if not cls._initialized: return
        attrs = {"reviewer_id": reviewer_id, "reviewer_decision": decision}
        if escalation_type: attrs["escalation_type"] = escalation_type
        cls._review_duration_hist.record(duration_ms, attrs)
        cls._queue_time_hist.record(queue_time_ms, attrs)

    @classmethod
    def record_sla_breach(cls, escalation_type: str) -> None:
        """Record a queue SLA breach for a human review."""
        if not cls._initialized: return
        cls._sla_breach_counter.add(1, {"escalation_type": escalation_type})
