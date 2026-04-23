"""
Tests for Telemetry Plugin Custom Attributes and System Precedence.
"""
import pytest
from unittest.mock import MagicMock, patch
import time

from adk_web_api.telemetry_plugin import (
    TelemetryPlugin,
    add_custom_attribute,
    get_custom_attributes,
    set_custom_attributes,
    _custom_attributes
)
from adk_web_api.telemetry import record_llm_metrics


@pytest.fixture
def clear_context():
    """Clear the context variables before each test to ensure isolation."""
    token = _custom_attributes.set({})
    yield
    _custom_attributes.reset(token)


class MockCallbackContext:
    def __init__(self, agent_name="test_agent"):
        self.agent_name = agent_name
        self.invocation_id = "inv-123"


class MockLlmRequest:
    def __init__(self, model="gemini-2.5-pro"):
        self.model = model
        self.contents = []


class MockLlmResponse:
    def __init__(self):
        self.usage_metadata = MagicMock()
        self.usage_metadata.prompt_token_count = 100
        self.usage_metadata.candidates_token_count = 50
        self.error_code = None
        self.error_message = None


class TestTelemetryCustomAttributes:
    
    def test_contextvar_isolation(self, clear_context):
        """Test that custom attributes are correctly stored and retrieved."""
        add_custom_attribute("tenant_id", "ulta_001")
        add_custom_attribute("user_tier", "premium")
        
        attrs = get_custom_attributes()
        assert attrs == {"tenant_id": "ulta_001", "user_tier": "premium"}
        
        # Ensure get_custom_attributes returns a copy so downstream modifications don't corrupt state
        attrs["hacked"] = True
        assert "hacked" not in get_custom_attributes()
        
    @patch("adk_web_api.telemetry.get_meter")
    def test_telemetry_system_precedence(self, mock_get_meter, clear_context):
        """Test that record_llm_metrics enforces system precedence over custom tags."""
        mock_meter = MagicMock()
        mock_get_meter.return_value = mock_meter
        
        custom_attrs = {
            "tenant_id": "ulta_001",
            "model": "fake-free-model",   # Malicious/accidental overwrite attempt
            "latency_ms": 1               # Malicious/accidental overwrite attempt
        }
        
        result = record_llm_metrics(
            model="gemini-2.5-pro",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1500.5,
            success=True,
            custom_attributes=custom_attrs
        )
        
        # Verify the returned dictionary successfully protected the system values
        assert result["tenant_id"] == "ulta_001"
        assert result["model"] == "gemini-2.5-pro"  # Protected!
        assert result["latency_ms"] == 1500.5       # Protected!
        
        # Verify the meter attributes also protected the system values
        mock_counter = mock_meter.create_counter.return_value
        call_args = mock_counter.add.call_args
        if call_args:
            emitted_attrs = call_args[0][1]
            assert emitted_attrs["model"] == "gemini-2.5-pro"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])