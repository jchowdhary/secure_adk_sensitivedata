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
    RetryTracker,
    FallbackTracker,
    SystemAndRuntimeMetrics,
    GovernanceAndRiskMetrics,
    DataAndOutputQualityMetrics,
    AgentBehaviorMetrics,
    HITLOperationsMetrics
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
# RETRY TRACKER TESTS
# =============================================================================

class TestRetryTracker:
    """Tests for retry tracking."""
    
    def setup_method(self):
        """Clear retry counts before each test."""
        RetryTracker._retry_counts = {}
    
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
    


# =============================================================================
# FALLBACK TRACKER TESTS
# =============================================================================

class TestFallbackTracker:
    """Tests for fallback tracking."""
    
    
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


# =============================================================================
# 1. SYSTEM AND RUNTIME METRICS TESTS
# =============================================================================

class TestSystemAndRuntimeMetrics:
    """Tests for system error and runtime tracking metrics."""
    
    def test_initialize_and_record_secret(self):
        """Test recording successful secret load."""
        mock_meter = MagicMock()
        SystemAndRuntimeMetrics.initialize(mock_meter)
        
        SystemAndRuntimeMetrics.record_secret_load(
            secret_id="test-secret",
            latency_ms=150.5,
            success=True
        )
        
        SystemAndRuntimeMetrics._secret_load_counter.add.assert_called()
        SystemAndRuntimeMetrics._secret_latency_hist.record.assert_called()

    def test_record_error(self):
        """Test recording categorized error."""
        mock_meter = MagicMock()
        SystemAndRuntimeMetrics.initialize(mock_meter)
        
        SystemAndRuntimeMetrics.record_error(
            category=ErrorCategory.RATE_LIMIT,
            error_code="429",
            correlation_id="corr-err",
            is_retryable=True,
            attributes={"tenant_id": "t-123"}
        )
        
        SystemAndRuntimeMetrics._error_counter.add.assert_called_once()
        call_args = SystemAndRuntimeMetrics._error_counter.add.call_args
        assert call_args[0][1]["category"] == "rate_limit"
        assert call_args[0][1]["tenant_id"] == "t-123"


# =============================================================================
# 2. GOVERNANCE AND RISK METRICS TESTS
# =============================================================================

class TestGovernanceAndRiskMetrics:
    """Tests for policy and safety tracking."""
    
    def test_record_policy_event(self):
        """Test recording policy violations like PII detected."""
        mock_meter = MagicMock()
        GovernanceAndRiskMetrics.initialize(mock_meter)
        
        GovernanceAndRiskMetrics.record_policy_event(
            policy_type="pii_detected",
            action_taken="mask",
            trigger_reason="US_SOCIAL_SECURITY_NUMBER",
            use_case="user_message"
        )
        
        GovernanceAndRiskMetrics._policy_counter.add.assert_called_once()
        args = GovernanceAndRiskMetrics._policy_counter.add.call_args[0][1]
        assert args["policy_type"] == "pii_detected"
        assert args["action_taken"] == "mask"
        assert args["use_case"] == "user_message"


# =============================================================================
# 3. DATA AND OUTPUT QUALITY METRICS TESTS
# =============================================================================

class TestDataAndOutputQualityMetrics:
    """Tests for output quality like groundedness and retrieval hits."""
    
    def test_record_groundedness(self):
        """Test recording groundedness score."""
        mock_meter = MagicMock()
        DataAndOutputQualityMetrics.initialize(mock_meter)
        
        DataAndOutputQualityMetrics.record_groundedness(
            score=0.92,
            use_case="knowledge_search",
            subagent_id="support_agent"
        )
        
        DataAndOutputQualityMetrics._groundedness_hist.record.assert_called_once()
        args = DataAndOutputQualityMetrics._groundedness_hist.record.call_args[0][1]
        assert args["use_case"] == "knowledge_search"
        assert args["subagent_id"] == "support_agent"

    def test_record_retrieval(self):
        """Test recording retrieval events."""
        mock_meter = MagicMock()
        DataAndOutputQualityMetrics.initialize(mock_meter)
        
        DataAndOutputQualityMetrics.record_retrieval(is_empty=False, cache_hit=True)
        
        DataAndOutputQualityMetrics._retrieval_counter.add.assert_called_once()
        args = DataAndOutputQualityMetrics._retrieval_counter.add.call_args[0][1]
        assert args["is_empty"] is False
        assert args["cache_hit"] is True


# =============================================================================
# 4. AGENT BEHAVIOR METRICS TESTS
# =============================================================================

class TestAgentBehaviorMetrics:
    """Tests for agent routing and decision logic."""
    
    def test_record_routing(self):
        """Test recording routing decisions."""
        mock_meter = MagicMock()
        AgentBehaviorMetrics.initialize(mock_meter)
        
        AgentBehaviorMetrics.record_routing(
            decision_type="delegate",
            confidence_score=0.85,
            target_agent="billing_agent"
        )
        
        AgentBehaviorMetrics._routing_counter.add.assert_called_once()
        AgentBehaviorMetrics._routing_confidence.record.assert_called_once_with(
            0.85, 
            {"decision_type": "delegate", "target_agent": "billing_agent"}
        )


# =============================================================================
# 5. HITL OPERATIONS METRICS TESTS
# =============================================================================

class TestHITLOperationsMetrics:
    """Tests for Human-In-The-Loop operations metrics."""
    
    def test_initialize(self):
        """Test that meters are initialized."""
        mock_meter = MagicMock()
        HITLOperationsMetrics.initialize(mock_meter)
        
        assert HITLOperationsMetrics._initialized is True
        assert mock_meter.create_counter.call_count == 3
        assert mock_meter.create_histogram.call_count == 2

    def test_record_escalation(self):
        """Test recording an escalation event."""
        mock_meter = MagicMock()
        HITLOperationsMetrics.initialize(mock_meter)
        
        HITLOperationsMetrics.record_escalation(
            escalation_type="safety_policy", 
            reason="high_risk_score", 
            agent_id="security_agent", 
            attributes={"region": "us-east"}
        )
        
        HITLOperationsMetrics._escalation_counter.add.assert_called_once_with(1, {
            "escalation_type": "safety_policy", 
            "escalation_reason": "high_risk_score", 
            "escalating_agent_id": "security_agent",
            "region": "us-east"
        })

    def test_record_review_completed(self):
        """Test recording a human review completion."""
        mock_meter = MagicMock()
        # Ensure create_histogram returns a distinct mock for each metric
        mock_meter.create_histogram.side_effect = lambda *args, **kwargs: MagicMock()
        HITLOperationsMetrics.initialize(mock_meter)
        
        HITLOperationsMetrics.record_review_completed(
            reviewer_id="user_123",
            duration_ms=45000,
            queue_time_ms=120000,
            decision="override",
            escalation_type="confidence"
        )
        
        HITLOperationsMetrics._review_duration_hist.record.assert_called_once()
        HITLOperationsMetrics._queue_time_hist.record.assert_called_once()


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestRecordAndCategorizeError:
    """Tests for SystemAndRuntimeMetrics.record_and_categorize convenience function."""
    
    def setup_method(self):
        """Clear callbacks and initialize metrics."""
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        SystemAndRuntimeMetrics.initialize(mock_meter)
    
    def test_records_and_returns_categorized_error(self):
        """Test that function records metrics and returns categorized error."""
        result = SystemAndRuntimeMetrics.record_and_categorize(
            error_code="RESOURCE_EXHAUSTED",
            error_message="Quota exceeded",
            correlation_id="corr-test"
        )
        
        assert isinstance(result, CategorizedError)
        assert result.category == ErrorCategory.RATE_LIMIT
        assert result.is_retryable is True


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for custom metrics."""
    
    def test_full_error_flow(self):
        """Test the full error categorization and tracking flow."""
        # Setup
        
        # Initialize metrics
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        SystemAndRuntimeMetrics.initialize(mock_meter)
        
        # Simulate error and retry
        correlation_id = "corr-integration"
        
        # Record error
        categorized = SystemAndRuntimeMetrics.record_and_categorize(
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
