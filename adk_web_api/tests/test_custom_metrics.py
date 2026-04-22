"""
Unit tests for custom_metrics module.

Tests cover:
- Error categorization
- CustomMetricsRegistry
- MetricsHooks
- RetryTracker
- FallbackTracker
- SecretManagerMetrics
- ErrorMetrics
"""
import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Import the module under test
import sys
sys.path.insert(0, '/home/jayant/ulta/ulta-code/adk_web_api')

from adk_web_api.custom_metrics import (
    ErrorCategory,
    CategorizedError,
    MetricType,
    MetricDefinition,
    CustomMetricsRegistry,
    MetricsHooks,
    RetryTracker,
    FallbackTracker,
    SecretManagerMetrics,
    HITLMetrics,
    ErrorMetrics,   
    record_error_with_category,
    initialize_custom_metrics,
)


# =============================================================================
# ERROR CATEGORIZATION TESTS
# =============================================================================

class TestErrorCategorization:
    """Tests for error categorization."""
    
    def test_rate_limit_error_from_code(self):
        """Test categorizing rate limit errors from error code."""
        error = CategorizedError.from_error(error_code="RESOURCE_EXHAUSTED")
        
        assert error.category == ErrorCategory.RATE_LIMIT
        assert error.is_retryable is True
        assert error.suggested_backoff_ms == 60000
    
    def test_rate_limit_error_from_code_429(self):
        """Test categorizing 429 errors."""
        error = CategorizedError.from_error(error_code="429")
        
        assert error.category == ErrorCategory.RATE_LIMIT
        assert error.is_retryable is True
    
    def test_timeout_error_from_message(self):
        """Test categorizing timeout errors from message."""
        error = CategorizedError.from_error(error_message="Request timed out after 30s")
        
        assert error.category == ErrorCategory.TIMEOUT
        assert error.is_retryable is True
        assert error.suggested_backoff_ms == 5000
    
    def test_authentication_error(self):
        """Test categorizing authentication errors."""
        error = CategorizedError.from_error(
            error_code="UNAUTHENTICATED",
            error_message="Invalid API key"
        )
        
        assert error.category == ErrorCategory.AUTHENTICATION
        assert error.is_retryable is False
        assert error.suggested_backoff_ms == 0
    
    def test_authorization_error(self):
        """Test categorizing permission denied errors."""
        error = CategorizedError.from_error(error_code="PERMISSION_DENIED")
        
        assert error.category == ErrorCategory.AUTHORIZATION
        assert error.is_retryable is False
    
    def test_content_filtered_error(self):
        """Test categorizing content safety errors."""
        error = CategorizedError.from_error(
            error_message="Content blocked due to safety guidelines"
        )
        
        assert error.category == ErrorCategory.CONTENT_FILTERED
        assert error.is_retryable is False
    
    def test_network_error(self):
        """Test categorizing network errors."""
        error = CategorizedError.from_error(
            error_code="UNAVAILABLE",
            error_message="Service temporarily unavailable"
        )
        
        assert error.category == ErrorCategory.NETWORK_ERROR
        assert error.is_retryable is True
        assert error.suggested_backoff_ms == 2000
    
    def test_internal_error(self):
        """Test categorizing internal server errors."""
        error = CategorizedError.from_error(
            error_code="INTERNAL",
            error_message="Internal server error"
        )
        
        assert error.category == ErrorCategory.INTERNAL_ERROR
        assert error.is_retryable is True
        assert error.suggested_backoff_ms == 1000
    
    def test_invalid_request_error(self):
        """Test categorizing invalid request errors."""
        error = CategorizedError.from_error(
            error_code="INVALID_ARGUMENT",
            error_message="Invalid parameter value"
        )
        
        assert error.category == ErrorCategory.INVALID_REQUEST
        assert error.is_retryable is False
    
    def test_model_not_found_error(self):
        """Test categorizing model not found errors."""
        error = CategorizedError.from_error(error_message="Model 'xyz' does not exist")
        
        assert error.category == ErrorCategory.MODEL_NOT_FOUND
        assert error.is_retryable is False
    
    def test_unknown_error(self):
        """Test categorizing unknown errors."""
        error = CategorizedError.from_error(
            error_message="Something weird happened"
        )
        
        assert error.category == ErrorCategory.UNKNOWN
        assert error.is_retryable is False
    
    def test_error_from_exception(self):
        """Test categorizing from actual exception object."""
        try:
            raise ValueError("Test error with timeout in message")
        except Exception as e:
            error = CategorizedError.from_error(error=e)
            
            assert error.category == ErrorCategory.TIMEOUT
            assert error.original_error == e
    
    def test_priority_of_error_code_over_message(self):
        """Test that error code has priority in categorization."""
        error = CategorizedError.from_error(
            error_code="UNAUTHENTICATED",
            error_message="timeout occurred"  # Would match timeout if code didn't exist
        )
        
        # Error code should take precedence
        assert error.category == ErrorCategory.AUTHENTICATION


# =============================================================================
# CUSTOM METRICS REGISTRY TESTS
# =============================================================================

class TestCustomMetricsRegistry:
    """Tests for custom metrics registry."""
    
    def test_singleton_pattern(self):
        """Test that registry is a singleton."""
        registry1 = CustomMetricsRegistry.get_instance()
        registry2 = CustomMetricsRegistry.get_instance()
        
        assert registry1 is registry2
    
    def test_register_counter(self):
        """Test registering a counter metric."""
        registry = CustomMetricsRegistry.get_instance()
        registry.register_counter(
            name="test.counter",
            description="Test counter",
            unit="count"
        )
        
        assert registry.is_registered("test.counter")
    
    def test_register_histogram(self):
        """Test registering a histogram metric."""
        registry = CustomMetricsRegistry.get_instance()
        registry.register_histogram(
            name="test.histogram",
            description="Test histogram",
            unit="ms"
        )
        
        assert registry.is_registered("test.histogram")
    
    def test_emit_counter_unregistered_raises(self):
        """Test that emitting unregistered counter raises error."""
        registry = CustomMetricsRegistry.get_instance()
        
        with pytest.raises(ValueError, match="not registered"):
            registry.emit_counter("nonexistent.metric")
    
    def test_emit_histogram_unregistered_raises(self):
        """Test that emitting unregistered histogram raises error."""
        registry = CustomMetricsRegistry.get_instance()
        
        with pytest.raises(ValueError, match="not registered"):
            registry.emit_histogram("nonexistent.metric", value=1.0)
    
    def test_emit_counter_with_attributes(self):
        """Test emitting counter with custom attributes."""
        registry = CustomMetricsRegistry.get_instance()
        
        # Register and initialize with mock meter
        registry.register_counter("test.counter_with_attrs", "Test")
        mock_counter = MagicMock()
        registry._counters["test.counter_with_attrs"] = mock_counter
        
        registry.emit_counter(
            "test.counter_with_attrs",
            value=5,
            attributes={"key": "value"}
        )
        
        mock_counter.add.assert_called_once_with(5, {"key": "value"})
    
    def test_emit_histogram_with_attributes(self):
        """Test emitting histogram with custom attributes."""
        registry = CustomMetricsRegistry.get_instance()
        
        registry.register_histogram("test.histogram_with_attrs", "Test")
        mock_histogram = MagicMock()
        registry._histograms["test.histogram_with_attrs"] = mock_histogram
        
        registry.emit_histogram(
            "test.histogram_with_attrs",
            value=123.45,
            attributes={"operation": "validate"}
        )
        
        mock_histogram.record.assert_called_once_with(123.45, {"operation": "validate"})


# =============================================================================
# METRICS HOOKS TESTS
# =============================================================================

class TestMetricsHooks:
    """Tests for metrics hooks callback system."""
    
    def setup_method(self):
        """Clear callbacks before each test."""
        MetricsHooks._llm_start_callbacks = []
        MetricsHooks._llm_end_callbacks = []
        MetricsHooks._tool_start_callbacks = []
        MetricsHooks._tool_end_callbacks = []
        MetricsHooks._error_callbacks = []
        MetricsHooks._retry_callbacks = []
        MetricsHooks._fallback_callbacks = []
    
    def test_on_llm_call_start(self):
        """Test registering LLM start callback."""
        callback = Mock()
        MetricsHooks.on_llm_call_start(callback)
        
        assert callback in MetricsHooks._llm_start_callbacks
    
    def test_on_llm_call_end(self):
        """Test registering LLM end callback."""
        callback = Mock()
        MetricsHooks.on_llm_call_end(callback)
        
        assert callback in MetricsHooks._llm_end_callbacks
    
    def test_on_error(self):
        """Test registering error callback."""
        callback = Mock()
        MetricsHooks.on_error(callback)
        
        assert callback in MetricsHooks._error_callbacks
    
    def test_trigger_llm_start(self):
        """Test triggering LLM start callbacks."""
        callback = Mock()
        MetricsHooks.on_llm_call_start(callback)
        
        MetricsHooks.trigger_llm_start({"model": "gemini-2.5-flash"})
        
        callback.assert_called_once_with("llm_call_start", {"model": "gemini-2.5-flash"})
    
    def test_trigger_llm_end(self):
        """Test triggering LLM end callbacks."""
        callback = Mock()
        MetricsHooks.on_llm_call_end(callback)
        
        MetricsHooks.trigger_llm_end({"success": True, "latency_ms": 100})
        
        callback.assert_called_once_with("llm_call_end", {"success": True, "latency_ms": 100})
    
    def test_trigger_error(self):
        """Test triggering error callbacks."""
        callback = Mock()
        MetricsHooks.on_error(callback)
        
        MetricsHooks.trigger_error({
            "category": "rate_limit",
            "is_retryable": True
        })
        
        callback.assert_called_once_with("error", {
            "category": "rate_limit",
            "is_retryable": True
        })
    
    def test_trigger_with_multiple_callbacks(self):
        """Test triggering multiple callbacks."""
        callback1 = Mock()
        callback2 = Mock()
        MetricsHooks.on_llm_call_end(callback1)
        MetricsHooks.on_llm_call_end(callback2)
        
        MetricsHooks.trigger_llm_end({"test": "data"})
        
        callback1.assert_called_once()
        callback2.assert_called_once()
    
    def test_callback_exception_does_not_break_flow(self):
        """Test that callback exceptions don't break the main flow."""
        bad_callback = Mock(side_effect=Exception("Callback error"))
        good_callback = Mock()
        MetricsHooks.on_llm_call_end(bad_callback)
        MetricsHooks.on_llm_call_end(good_callback)
        
        # Should not raise, and good callback should still be called
        MetricsHooks.trigger_llm_end({"test": "data"})
        
        good_callback.assert_called_once()


# =============================================================================
# RETRY TRACKER TESTS
# =============================================================================

class TestRetryTracker:
    """Tests for retry tracking."""
    
    def setup_method(self):
        """Clear retry counts before each test."""
        RetryTracker._retry_counts = {}
        MetricsHooks._retry_callbacks = []
    
    def test_record_retry_attempt(self):
        """Test recording a retry attempt."""
        event = RetryTracker.record_retry_attempt(
            correlation_id="corr-123",
            error_code="RESOURCE_EXHAUSTED",
            error_message="Rate limit exceeded"
        )
        
        assert event.attempt_number == 1
        assert event.max_attempts == 3
        assert event.error_category == ErrorCategory.RATE_LIMIT
        assert event.correlation_id == "corr-123"
    
    def test_incrementing_attempts(self):
        """Test that attempts increment correctly."""
        correlation_id = "corr-456"
        
        event1 = RetryTracker.record_retry_attempt(correlation_id)
        event2 = RetryTracker.record_retry_attempt(correlation_id)
        event3 = RetryTracker.record_retry_attempt(correlation_id)
        
        assert event1.attempt_number == 1
        assert event2.attempt_number == 2
        assert event3.attempt_number == 3
    
    def test_exponential_backoff(self):
        """Test that backoff increases exponentially."""
        correlation_id = "corr-789"
        
        # Rate limit error has 60000ms base backoff
        event1 = RetryTracker.record_retry_attempt(
            correlation_id, 
            error_code="RESOURCE_EXHAUSTED"
        )
        event2 = RetryTracker.record_retry_attempt(
            correlation_id,
            error_code="RESOURCE_EXHAUSTED"
        )
        event3 = RetryTracker.record_retry_attempt(
            correlation_id,
            error_code="RESOURCE_EXHAUSTED"
        )
        
        assert event1.backoff_ms == 60000  # 60000 * 2^0
        assert event2.backoff_ms == 120000  # 60000 * 2^1
        assert event3.backoff_ms == 240000  # 60000 * 2^2
    
    def test_reset_retry_count(self):
        """Test resetting retry count for a correlation ID."""
        correlation_id = "corr-reset"
        
        RetryTracker.record_retry_attempt(correlation_id)
        assert RetryTracker._retry_counts.get(correlation_id) == 1
        
        RetryTracker.reset(correlation_id)
        assert correlation_id not in RetryTracker._retry_counts
    
    def test_retry_triggers_hooks(self):
        """Test that retry events trigger hooks."""
        callback = Mock()
        MetricsHooks.on_retry(callback)
        
        RetryTracker.record_retry_attempt(
            correlation_id="corr-hook",
            error_code="TIMEOUT"
        )
        
        callback.assert_called_once()
        call_data = callback.call_args[0][1]
        assert call_data["attempt_number"] == 1
        assert call_data["error_category"] == "timeout"


# =============================================================================
# FALLBACK TRACKER TESTS
# =============================================================================

class TestFallbackTracker:
    """Tests for fallback tracking."""
    
    def setup_method(self):
        """Clear callbacks before each test."""
        MetricsHooks._fallback_callbacks = []
    
    def test_record_fallback(self):
        """Test recording a fallback event."""
        event = FallbackTracker.record_fallback(
            fallback_type="model",
            original_value="gemini-2.5-pro",
            fallback_value="gemini-2.5-flash",
            reason="Rate limit on pro model",
            correlation_id="corr-fallback"
        )
        
        assert event.fallback_type == "model"
        assert event.original_value == "gemini-2.5-pro"
        assert event.fallback_value == "gemini-2.5-flash"
        assert event.reason == "Rate limit on pro model"
    
    def test_fallback_triggers_hooks(self):
        """Test that fallback events trigger hooks."""
        callback = Mock()
        MetricsHooks.on_fallback(callback)
        
        FallbackTracker.record_fallback(
            fallback_type="region",
            original_value="us-central1",
            fallback_value="us-east1",
            reason="Region outage"
        )
        
        callback.assert_called_once()
        call_data = callback.call_args[0][1]
        assert call_data["fallback_type"] == "region"
        assert call_data["reason"] == "Region outage"


# =============================================================================
# SECRET MANAGER METRICS TESTS
# =============================================================================

class TestSecretManagerMetrics:
    """Tests for Secret Manager metrics."""
    
    def test_initialize(self):
        """Test initializing Secret Manager metrics."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        
        mock_meter.create_counter.return_value = mock_counter
        mock_meter.create_histogram.return_value = mock_histogram
        
        SecretManagerMetrics.initialize(mock_meter)
        
        assert SecretManagerMetrics._initialized is True
        mock_meter.create_counter.assert_called()
        mock_meter.create_histogram.assert_called()
    
    def test_record_load_success(self):
        """Test recording successful secret load."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        
        mock_meter.create_counter.return_value = mock_counter
        mock_meter.create_histogram.return_value = mock_histogram
        
        SecretManagerMetrics.initialize(mock_meter)
        SecretManagerMetrics.record_load(
            secret_id="test-secret",
            latency_ms=150.5,
            success=True
        )
        
        mock_counter.add.assert_called()
        mock_histogram.record.assert_called()
    
    def test_record_load_error(self):
        """Test recording failed secret load."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        
        mock_meter.create_counter.return_value = mock_counter
        mock_meter.create_histogram.return_value = mock_histogram
        
        SecretManagerMetrics.initialize(mock_meter)
        SecretManagerMetrics.record_load(
            secret_id="test-secret",
            latency_ms=50.0,
            success=False,
            error="NOT_FOUND"
        )
        
        # Should be called twice: once for load, once for error
        assert mock_counter.add.call_count == 2


# =============================================================================
# ERROR METRICS TESTS
# =============================================================================

class TestErrorMetrics:
    """Tests for error metrics."""
    
    def test_record_error(self):
        """Test recording categorized error."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        
        ErrorMetrics.initialize(mock_meter)
        ErrorMetrics.record_error(
            category=ErrorCategory.RATE_LIMIT,
            error_code="429",
            correlation_id="corr-err",
            is_retryable=True
        )
        
        mock_counter.add.assert_called_once()
        call_args = mock_counter.add.call_args
        assert "category" in call_args[0][1]
        assert call_args[0][1]["category"] == "rate_limit"
    
    def test_record_retry(self):
        """Test recording retry metric."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        
        ErrorMetrics.initialize(mock_meter)
        ErrorMetrics.record_retry(
            attempt_number=2,
            category=ErrorCategory.TIMEOUT,
            correlation_id="corr-retry"
        )
        
        mock_counter.add.assert_called_once()
    
    def test_record_fallback(self):
        """Test recording fallback metric."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        
        ErrorMetrics.initialize(mock_meter)
        ErrorMetrics.record_fallback(
            fallback_type="model",
            reason="Rate limit exceeded",
            correlation_id="corr-fallback"
        )
        
        mock_counter.add.assert_called_once()


# =============================================================================
# HITL METRICS TESTS
# =============================================================================

class TestHITLMetrics:
    """Tests for Human-In-The-Loop metrics."""
    
    def test_initialize(self):
        mock_meter = MagicMock()
        HITLMetrics.initialize(mock_meter)
        
        assert HITLMetrics._initialized is True
        assert mock_meter.create_counter.call_count == 2
        assert mock_meter.create_histogram.call_count == 2

    def test_record_escalation(self):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        
        HITLMetrics.initialize(mock_meter)
        HITLMetrics.record_escalation("safety_policy", "high_risk_score", "security_agent")
        
        mock_counter.add.assert_called_once_with(1, {
            "escalation_type": "safety_policy", 
            "escalation_reason": "high_risk_score", 
            "escalating_agent_id": "security_agent"
        })

    def test_record_review_completed(self):
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram.return_value = mock_hist
        
        HITLMetrics.initialize(mock_meter)
        HITLMetrics.record_review_completed(
            reviewer_id="user_123",
            duration_ms=45000,
            queue_time_ms=120000,
            decision="override",
            escalation_type="confidence"
        )
        
        # Should be called twice (once for duration, once for queue time)
        assert mock_hist.record.call_count == 2
        
        # Verify one of the calls contains the right attributes
        call_args = mock_hist.record.call_args_list[0]
        assert call_args[0][1]["reviewer_id"] == "user_123"
        assert call_args[0][1]["reviewer_decision"] == "override"
        assert call_args[0][1]["escalation_type"] == "confidence"


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestRecordAndCategorizeError:
    """Tests for ErrorMetrics.record_and_categorize convenience function."""
    
    def setup_method(self):
        """Clear callbacks and initialize metrics."""
        MetricsHooks._error_callbacks = []
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        ErrorMetrics.initialize(mock_meter)
    
    def test_records_and_returns_categorized_error(self):
        """Test that function records metrics and returns categorized error."""
        result = ErrorMetrics.record_and_categorize(
            error_code="RESOURCE_EXHAUSTED",
            error_message="Quota exceeded",
            correlation_id="corr-test"
        )
        
        assert isinstance(result, CategorizedError)
        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.is_retryable is True
    
    def test_triggers_error_hooks(self):
        """Test that function triggers error hooks."""
        callback = Mock()
        MetricsHooks.on_error(callback)
        
        ErrorMetrics.record_and_categorize(
            error_code="TIMEOUT",
            correlation_id="corr-hook"
        )
        
        callback.assert_called_once()


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for custom metrics."""
    
    def test_full_error_flow(self):
        """Test the full error categorization and tracking flow."""
        # Setup
        MetricsHooks._error_callbacks = []
        MetricsHooks._retry_callbacks = []
        error_callback = Mock()
        retry_callback = Mock()
        MetricsHooks.on_error(error_callback)
        MetricsHooks.on_retry(retry_callback)
        
        # Initialize metrics
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        ErrorMetrics.initialize(mock_meter)
        
        # Simulate error and retry
        correlation_id = "corr-integration"
        
        # Record error
        categorized = ErrorMetrics.record_and_categorize(
            error_code="RESOURCE_EXHAUSTED",
            error_message="Rate limit exceeded",
            correlation_id=correlation_id
        )
        
        # Record retry
        retry_event = RetryTracker.record_retry_attempt(
            correlation_id=correlation_id,
            error_code="RESOURCE_EXHAUSTED"
        )
        
        # Verify
        assert categorized.category == ErrorCategory.RATE_LIMIT
        assert retry_event.attempt_number == 1
        error_callback.assert_called_once()
        retry_callback.assert_called_once()
    
    def test_custom_metric_registration_and_emission(self):
        """Test registering and emitting custom metrics."""
        registry = CustomMetricsRegistry.get_instance()
        
        # Register custom metrics
        registry.register_counter(
            name="test.business_operations",
            description="Business operation count",
            unit="ops"
        )
        
        registry.register_histogram(
            name="test.business_latency",
            description="Business operation latency",
            unit="ms"
        )
        
        # Create mock instruments
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        registry._counters["test.business_operations"] = mock_counter
        registry._histograms["test.business_latency"] = mock_histogram
        
        # Emit metrics
        registry.emit_counter(
            "test.business_operations",
            value=1,
            attributes={"operation": "checkout", "status": "success"}
        )
        
        registry.emit_histogram(
            "test.business_latency",
            value=123.45,
            attributes={"operation": "checkout"}
        )
        
        # Verify
        mock_counter.add.assert_called_once_with(
            1, {"operation": "checkout", "status": "success"}
        )
        mock_histogram.record.assert_called_once_with(
            123.45, {"operation": "checkout"}
        )


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
