"""
Interactive Tests for DLP Plugin with Mocked ADK Components

Run tests with verbose output:
    pytest test_dlp_plugin_interactive.py -v -s

Run specific test:
    pytest test_dlp_plugin_interactive.py::TestDLPPluginInteractive::test_user_message_masking -v -s

Run all tests:
    pytest test_dlp_plugin_interactive.py -v -s
"""
import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock
from dataclasses import dataclass, field
import sys

# Import DLP config modules first (no ADK dependencies)
from adk_web_api.dlp_config import (
    DLPSettings, 
    DLPProvider, 
    DLPAction, 
    InfoTypeConfig,
    DLPProfiles
)


# ============================================================================
# Mock ADK Types and Classes (defined BEFORE importing plugin)
# ============================================================================

class MockPart:
    """Mock google.genai.types.Part"""
    def __init__(self, text: str = ""):
        self.text = text


class MockContent:
    """Mock google.genai.types.Content"""
    def __init__(self, role: str = "user", parts: List[MockPart] = None):
        self.role = role
        self.parts = parts if parts is not None else [MockPart()]


class MockSession:
    """Mock ADK Session"""
    def __init__(self, id: str = "test-session-123"):
        self.id = id


class MockInvocationContext:
    """Mock ADK InvocationContext"""
    def __init__(self, invocation_id: str = "test-invocation-123", user_id: str = "test-user-123", session: MockSession = None):
        self.invocation_id = invocation_id
        self.user_id = user_id
        self.session = session if session else MockSession()


class MockCallbackContext:
    """Mock ADK CallbackContext"""
    def __init__(self, agent_name: str = "test-agent", invocation_id: str = "test-invocation-123"):
        self.agent_name = agent_name
        self.invocation_id = invocation_id


class MockLlmRequest:
    """Mock ADK LlmRequest"""
    def __init__(self, model: str = "gemini-pro", contents: List[MockContent] = None):
        self.model = model
        self.contents = contents if contents is not None else []


class MockLlmResponse:
    """Mock ADK LlmResponse"""
    def __init__(self, content: MockContent = None, error_code: str = None, error_message: str = None):
        self.content = content
        self.error_code = error_code
        self.error_message = error_message


class MockTool:
    """Mock ADK BaseTool"""
    def __init__(self, name: str = "test_tool"):
        self.name = name


class MockToolContext:
    """Mock ADK ToolContext"""
    def __init__(self, agent_name: str = "test-agent", invocation_id: str = "test-invocation-123"):
        self.agent_name = agent_name
        self.invocation_id = invocation_id


class MockBasePlugin:
    """Mock BasePlugin class for ADK"""
    def __init__(self, name: str = "plugin"):
        self.name = name


# Setup mock modules BEFORE importing dlp_plugin
mock_types = MagicMock()
mock_types.Part = MockPart
mock_types.Content = MockContent

mock_genai = MagicMock()
mock_genai.types = mock_types

mock_base_plugin = MagicMock()
mock_base_plugin.BasePlugin = MockBasePlugin

mock_callback_context = MagicMock()
mock_callback_context.CallbackContext = MockCallbackContext

mock_invocation_context = MagicMock()
mock_invocation_context.InvocationContext = MockInvocationContext

mock_llm_request = MagicMock()
mock_llm_request.LlmRequest = MockLlmRequest

mock_llm_response = MagicMock()
mock_llm_response.LlmResponse = MockLlmResponse

mock_base_tool = MagicMock()
mock_base_tool.BaseTool = MockTool

mock_tool_context = MagicMock()
mock_tool_context.ToolContext = MockToolContext

# Inject mocks into sys.modules
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = mock_types
sys.modules['google.adk.plugins.base_plugin'] = mock_base_plugin
sys.modules['google.adk.agents.callback_context'] = mock_callback_context
sys.modules['google.adk.agents.invocation_context'] = mock_invocation_context
sys.modules['google.adk.models.llm_request'] = mock_llm_request
sys.modules['google.adk.models.llm_response'] = mock_llm_response
sys.modules['google.adk.tools.base_tool'] = mock_base_tool
sys.modules['google.adk.tools.tool_context'] = mock_tool_context

# NOW import the plugin (after mocks are set up)
from adk_web_api.dlp_plugin import DLPPlugin, create_dlp_plugin


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def basic_settings():
    """Basic DLP settings for regex-based detection."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=[
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_SOCIAL_SECURITY_NUMBER",
            "CREDIT_CARD_NUMBER",
            "IP_ADDRESS",
        ],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
    )


@pytest.fixture
def redact_settings():
    """DLP settings for redact action."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REDACT,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
    )


@pytest.fixture
def hash_settings():
    """DLP settings for hash action."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.HASH,
        info_types=["EMAIL_ADDRESS", "US_SOCIAL_SECURITY_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
    )


@pytest.fixture
def replace_settings():
    """DLP settings for replace action."""
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REPLACE,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
    )
    settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
        name="EMAIL_ADDRESS",
        custom_replacement="[EMAIL REDACTED]"
    )
    settings.info_type_configs["PHONE_NUMBER"] = InfoTypeConfig(
        name="PHONE_NUMBER",
        custom_replacement="[PHONE REDACTED]"
    )
    return settings


@pytest.fixture
def alert_settings():
    """DLP settings for alert action (detect only, no modification)."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.ALERT,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
    )


@pytest.fixture
def disabled_scopes_settings():
    """DLP settings with all scanning disabled."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS"],
        scan_user_messages=False,
        scan_llm_requests=False,
        scan_llm_responses=False,
        scan_tool_calls=False,
        scan_tool_results=False,
    )


# ============================================================================
# Test Class for Interactive DLP Plugin Testing
# ============================================================================

class TestDLPPluginInteractive:
    """
    Interactive tests for DLP Plugin with mocked ADK components.
    
    These tests verify the plugin's callback methods work correctly
    with various DLP actions and configurations.
    """
    
    # ------------------------------------------------------------------------
    # User Message Callback Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_user_message_masking(self, basic_settings, capsys):
        """Test masking of PII in user messages."""
        print("\n" + "="*60)
        print("  TEST: User Message Masking")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        # Create mock user message with PII
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="My email is john@example.com and phone is (555) 123-4567")]
        )
        
        invocation_context = MockInvocationContext()
        
        # Process the message
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        # Verify result
        assert result is not None
        assert len(result.parts) == 1
        assert "j***@example.com" in result.parts[0].text
        assert "(***) ***-****" in result.parts[0].text
        assert "john@example.com" not in result.parts[0].text
        
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Masked:   {result.parts[0].text}")
        print("\n✓ User message masking works correctly")
    
    @pytest.mark.asyncio
    async def test_user_message_redact(self, redact_settings, capsys):
        """Test redaction (complete removal) of PII in user messages."""
        print("\n" + "="*60)
        print("  TEST: User Message Redaction")
        print("="*60)
        
        plugin = DLPPlugin(settings=redact_settings)
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Contact john@example.com or call (555) 123-4567")]
        )
        
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        assert "john@example.com" not in result.parts[0].text
        assert "(555) 123-4567" not in result.parts[0].text
        
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Redacted: {result.parts[0].text}")
        print("\n✓ User message redaction works correctly")
    
    @pytest.mark.asyncio
    async def test_user_message_hash(self, hash_settings, capsys):
        """Test hashing of PII in user messages."""
        print("\n" + "="*60)
        print("  TEST: User Message Hashing")
        print("="*60)
        
        plugin = DLPPlugin(settings=hash_settings)
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="SSN: 123-45-6789")]
        )
        
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        assert "123-45-6789" not in result.parts[0].text
        assert "...***" in result.parts[0].text
        
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Hashed:   {result.parts[0].text}")
        print("\n✓ User message hashing works correctly")
    
    @pytest.mark.asyncio
    async def test_user_message_replace(self, replace_settings, capsys):
        """Test custom replacement of PII in user messages."""
        print("\n" + "="*60)
        print("  TEST: User Message Custom Replacement")
        print("="*60)
        
        plugin = DLPPlugin(settings=replace_settings)
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Contact john@example.com or (555) 123-4567")]
        )
        
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        assert "[EMAIL REDACTED]" in result.parts[0].text
        assert "[PHONE REDACTED]" in result.parts[0].text
        
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Replaced: {result.parts[0].text}")
        print("\n✓ User message custom replacement works correctly")
    
    @pytest.mark.asyncio
    async def test_user_message_alert(self, alert_settings, capsys):
        """Test alert action (detect but don't modify)."""
        print("\n" + "="*60)
        print("  TEST: User Message Alert (Detect Only)")
        print("="*60)
        
        plugin = DLPPlugin(settings=alert_settings)
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Email: john@example.com with card 4111 1111 1111 1111")]
        )
        
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        # Alert action should NOT modify the text
        assert result is not None
        assert "john@example.com" in result.parts[0].text
        assert "4111 1111 1111 1111" in result.parts[0].text
        
        print(f"\nOriginal:  {user_message.parts[0].text}")
        print(f"Unchanged: {result.parts[0].text}")
        print("\n✓ Alert action works correctly (text unchanged, detection logged)")
    
    # ------------------------------------------------------------------------
    # LLM Request/Response Callback Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_llm_request_masking(self, basic_settings, capsys):
        """Test masking of PII in LLM requests."""
        print("\n" + "="*60)
        print("  TEST: LLM Request Masking")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        llm_request = MockLlmRequest(
            model="gemini-pro",
            contents=[
                MockContent(
                    role="user",
                    parts=[MockPart(text="Search for john@example.com")]
                )
            ]
        )
        
        callback_context = MockCallbackContext()
        
        result = await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request
        )
        
        # Should return None (not blocking the request)
        assert result is None
        # But the request should be modified
        assert "j***@example.com" in llm_request.contents[0].parts[0].text
        
        print(f"\nOriginal: Search for john@example.com")
        print(f"Masked:   {llm_request.contents[0].parts[0].text}")
        print("\n✓ LLM request masking works correctly")
    
    @pytest.mark.asyncio
    async def test_llm_response_masking(self, basic_settings, capsys):
        """Test masking of PII in LLM responses."""
        print("\n" + "="*60)
        print("  TEST: LLM Response Masking")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        llm_response = MockLlmResponse(
            content=MockContent(
                role="assistant",
                parts=[MockPart(text="Found user with email john@example.com")]
            )
        )
        
        callback_context = MockCallbackContext()
        
        result = await plugin.after_model_callback(
            callback_context=callback_context,
            llm_response=llm_response
        )
        
        # Should return None (not blocking the response)
        assert result is None
        # But the response should be modified
        assert "j***@example.com" in llm_response.content.parts[0].text
        
        print(f"\nOriginal: Found user with email john@example.com")
        print(f"Masked:   {llm_response.content.parts[0].text}")
        print("\n✓ LLM response masking works correctly")
    
    # ------------------------------------------------------------------------
    # Tool Callback Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_tool_call_masking(self, basic_settings, capsys):
        """Test masking of PII in tool call arguments."""
        print("\n" + "="*60)
        print("  TEST: Tool Call Argument Masking")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        tool = MockTool(name="search_users")
        tool_args = {
            "query": "Find user with email john@example.com",
            "phone_filter": "(555) 123-4567",
            "ssn_lookup": "123-45-6789",
            "limit": 100,
            "active": True
        }
        tool_context = MockToolContext()
        
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context
        )
        
        # Should return None to let tool proceed with modified args
        assert result is None
        # Args should be modified
        assert "j***@example.com" in tool_args["query"]
        assert "(***) ***-****" in tool_args["phone_filter"]
        assert "***-**-****" in tool_args["ssn_lookup"]
        # Non-string args should be unchanged
        assert tool_args["limit"] == 100
        assert tool_args["active"] is True
        
        print(f"\nOriginal Arguments:")
        print(f"  query: Find user with email john@example.com")
        print(f"  phone_filter: (555) 123-4567")
        print(f"  ssn_lookup: 123-45-6789")
        print(f"\nMasked Arguments:")
        print(f"  query: {tool_args['query']}")
        print(f"  phone_filter: {tool_args['phone_filter']}")
        print(f"  ssn_lookup: {tool_args['ssn_lookup']}")
        print("\n✓ Tool call argument masking works correctly")
    
    @pytest.mark.asyncio
    async def test_tool_result_masking(self, basic_settings, capsys):
        """Test masking of PII in tool results."""
        print("\n" + "="*60)
        print("  TEST: Tool Result Masking")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        tool = MockTool(name="get_user_info")
        tool_args = {"user_id": "123"}
        tool_context = MockToolContext()
        result_data = {
            "email": "john@example.com",
            "phone": "(555) 123-4567",
            "ssn": "123-45-6789",
            "status": "active"
        }
        
        masked_result = await plugin.after_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context,
            result=result_data
        )
        
        # Should return masked result
        assert masked_result is not None
        assert "j***@example.com" in masked_result["email"]
        assert "(***) ***-****" in masked_result["phone"]
        assert "***-**-****" in masked_result["ssn"]
        assert masked_result["status"] == "active"
        
        print(f"\nOriginal Result:")
        print(f"  email: john@example.com")
        print(f"  phone: (555) 123-4567")
        print(f"  ssn: 123-45-6789")
        print(f"\nMasked Result:")
        print(f"  email: {masked_result['email']}")
        print(f"  phone: {masked_result['phone']}")
        print(f"  ssn: {masked_result['ssn']}")
        print("\n✓ Tool result masking works correctly")
    
    # ------------------------------------------------------------------------
    # Scope Control Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_disabled_scopes(self, disabled_scopes_settings, capsys):
        """Test that scanning can be disabled for all scopes."""
        print("\n" + "="*60)
        print("  TEST: Disabled Scopes")
        print("="*60)
        
        plugin = DLPPlugin(settings=disabled_scopes_settings)
        
        # Test user message - should NOT be modified
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Email: john@example.com")]
        )
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        assert result == user_message  # Should return unchanged
        
        # Test tool call - should NOT be modified
        tool = MockTool(name="test")
        tool_args = {"email": "john@example.com"}
        tool_context = MockToolContext()
        
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context
        )
        assert result is None
        assert tool_args["email"] == "john@example.com"  # Unchanged
        
        print("\nAll scopes disabled - PII is NOT masked")
        print(f"User message: {user_message.parts[0].text} (unchanged)")
        print(f"Tool args: {tool_args} (unchanged)")
        print("\n✓ Scope control works correctly")
    
    # ------------------------------------------------------------------------
    # Multiple Info Types Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_multiple_info_types_combined(self, basic_settings, capsys):
        """Test detection of multiple info types in a single message."""
        print("\n" + "="*60)
        print("  TEST: Multiple Info Types in Single Message")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        text = """
        Contact Information:
        Email: john@example.com
        Phone: (555) 123-4567
        SSN: 123-45-6789
        Card: 4111 1111 1111 1111
        IP: 192.168.1.1
        """
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text=text)]
        )
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        result_text = result.parts[0].text
        
        # All PII should be masked
        assert "john@example.com" not in result_text
        assert "(555) 123-4567" not in result_text
        assert "123-45-6789" not in result_text
        assert "4111 1111 1111 1111" not in result_text
        assert "192.168.1.1" not in result_text
        
        print(f"\nOriginal Text:{text}")
        print(f"\nMasked Text:{result_text}")
        print("\n✓ Multiple info types detected and masked correctly")
    
    # ------------------------------------------------------------------------
    # Edge Cases Tests
    # ------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_empty_content(self, basic_settings, capsys):
        """Test handling of empty content."""
        print("\n" + "="*60)
        print("  TEST: Empty Content Handling")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        # Test empty parts
        user_message = MockContent(role="user", parts=[])
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        # Should return the original content
        assert result == user_message
        
        print("\n✓ Empty content handled correctly")
    
    @pytest.mark.asyncio
    async def test_no_pii_content(self, basic_settings, capsys):
        """Test handling of content with no PII."""
        print("\n" + "="*60)
        print("  TEST: No PII Content Handling")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="This is just regular text with no sensitive data")]
        )
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        # Should return the original content unchanged
        assert result.parts[0].text == user_message.parts[0].text
        
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Result:   {result.parts[0].text}")
        print("\n✓ No PII content handled correctly (unchanged)")
    
    @pytest.mark.asyncio
    async def test_nested_dict_in_tool_result(self, basic_settings, capsys):
        """Test handling of nested dictionaries in tool results."""
        print("\n" + "="*60)
        print("  TEST: Nested Dict in Tool Result")
        print("="*60)
        
        plugin = DLPPlugin(settings=basic_settings)
        
        tool = MockTool(name="get_user")
        tool_args = {}
        tool_context = MockToolContext()
        result_data = {
            "user": {
                "email": "john@example.com",
                "contact": {
                    "phone": "(555) 123-4567"
                }
            },
            "status": "active"
        }
        
        masked_result = await plugin.after_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context,
            result=result_data
        )
        
        assert masked_result is not None
        assert "j***@example.com" in masked_result["user"]["email"]
        assert "(***) ***-****" in masked_result["user"]["contact"]["phone"]
        assert masked_result["status"] == "active"
        
        print(f"\nOriginal Nested Result:")
        print(f"  user.email: john@example.com")
        print(f"  user.contact.phone: (555) 123-4567")
        print(f"\nMasked Nested Result:")
        print(f"  user.email: {masked_result['user']['email']}")
        print(f"  user.contact.phone: {masked_result['user']['contact']['phone']}")
        print("\n✓ Nested dict handling works correctly")


# ============================================================================
# Test Plugin Factory Function
# ============================================================================

class TestDLPPluginFactory:
    """Test the create_dlp_plugin factory function."""
    
    def test_create_basic_plugin(self, capsys):
        """Test creating plugin with basic profile."""
        print("\n" + "="*60)
        print("  TEST: Create Plugin with Basic Profile")
        print("="*60)
        
        plugin = create_dlp_plugin(profile="basic")
        
        assert plugin is not None
        assert plugin.settings.provider == DLPProvider.REGEX
        assert len(plugin.settings.info_types) == 4
        
        print(f"\nCreated plugin with basic profile:")
        print(f"  Provider: {plugin.settings.provider.value}")
        print(f"  Action: {plugin.settings.action.value}")
        print(f"  Info Types: {plugin.settings.info_types}")
        print("\n✓ Basic plugin creation works")
    
    def test_create_custom_settings_plugin(self, capsys):
        """Test creating plugin with custom settings."""
        print("\n" + "="*60)
        print("  TEST: Create Plugin with Custom Settings")
        print("="*60)
        
        custom_settings = DLPSettings(
            provider=DLPProvider.REGEX,
            action=DLPAction.HASH,
            info_types=["EMAIL_ADDRESS"]
        )
        
        plugin = create_dlp_plugin(settings=custom_settings)
        
        assert plugin is not None
        assert plugin.settings.action == DLPAction.HASH
        assert plugin.settings.info_types == ["EMAIL_ADDRESS"]
        
        print(f"\nCreated plugin with custom settings:")
        print(f"  Action: {plugin.settings.action.value}")
        print(f"  Info Types: {plugin.settings.info_types}")
        print("\n✓ Custom settings plugin creation works")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
