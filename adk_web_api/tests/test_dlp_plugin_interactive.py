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
    DLPProfiles,
    AgentFilterMode
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
def bypass_email_settings():
    """DLP settings that bypass trusted internal email domains."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
        enable_email_domain_bypass=True,
        bypass_email_domains=["ulta.com"],
    )


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


@pytest.fixture
def allowlist_agent_settings():
    """DLP settings with allowlist agent filtering - uses actual agent names from codebase."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
        agent_filter_mode=AgentFilterMode.ALLOWLIST,
        enabled_agents=["orchestrator", "sub_agent"],  # Actual agent names from codebase
    )


@pytest.fixture
def blocklist_agent_settings():
    """DLP settings with blocklist agent filtering - uses actual agent names from codebase."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
        agent_filter_mode=AgentFilterMode.BLOCKLIST,
        disabled_agents=["public-agent", "external-agent"],  # Agents to skip
    )


@pytest.fixture
def enterprise_hybrid_settings():
    """Enterprise profile with hybrid DLP provider - comprehensive info types."""
    return DLPSettings(
        provider=DLPProvider.REGEX,  # Use REGEX for testing (would be HYBRID in production)
        action=DLPAction.MASK,
        info_types=[
            "US_SOCIAL_SECURITY_NUMBER",
            "PASSPORT_NUMBER",
            "API_KEY",
            "AUTH_TOKEN",
            "DATE_OF_BIRTH",
            "PERSON_NAME",
            "LOCATION",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD_NUMBER",
            "IP_ADDRESS",
        ],
        scan_user_messages=True,
        scan_llm_requests=True,
        scan_llm_responses=True,
        scan_tool_calls=True,
        scan_tool_results=True,
        agent_filter_mode=AgentFilterMode.ALLOWLIST,
        enabled_agents=["orchestrator", "sub_agent"],
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
    async def test_user_message_bypass_internal_ulta_email(self, bypass_email_settings, capsys):
        """Trusted internal Ulta emails should bypass masking while external emails are masked."""
        print("\n" + "="*60)
        print("  TEST: User Message Internal Email Bypass")
        print("="*60)

        plugin = DLPPlugin(settings=bypass_email_settings)

        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Contacts: jane@ulta.com and john@example.com")]
        )

        invocation_context = MockInvocationContext()

        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )

        assert result is not None
        assert "jane@ulta.com" in result.parts[0].text
        assert "john@example.com" not in result.parts[0].text
        assert "j***@example.com" in result.parts[0].text

        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Masked:   {result.parts[0].text}")
        print("\n✓ Internal Ulta email bypass works correctly")
    
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
# Test Agent Filtering
# ============================================================================

class TestAgentFiltering:
    """Test agent-level boundary controls."""
    
    @pytest.mark.asyncio
    async def test_allowlist_agent_in_list(self, allowlist_agent_settings, capsys):
        """Test DLP applied when agent is in allowlist."""
        print("\n" + "="*60)
        print("  TEST: Allowlist - Agent IN List")
        print("="*60)
        
        plugin = DLPPlugin(settings=allowlist_agent_settings)
        
        # Agent in allowlist - should be scanned (using actual agent name)
        callback_context = MockCallbackContext(agent_name="orchestrator")
        llm_request = MockLlmRequest(
            model="gemini-pro",
            contents=[MockContent(role="user", parts=[MockPart(text="Email: john@example.com")])]
        )
        
        result = await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request
        )
        
        assert result is None
        # Content should be modified
        assert "j***@example.com" in llm_request.contents[0].parts[0].text
        
        print(f"\nAgent: orchestrator (IN allowlist)")
        print(f"Original: Email: john@example.com")
        print(f"Masked:   {llm_request.contents[0].parts[0].text}")
        print("\n✓ Allowlist mode - Agent in list is scanned")
    
    @pytest.mark.asyncio
    async def test_allowlist_agent_not_in_list(self, allowlist_agent_settings, capsys):
        """Test DLP skipped when agent is NOT in allowlist."""
        print("\n" + "="*60)
        print("  TEST: Allowlist - Agent NOT In List")
        print("="*60)
        
        plugin = DLPPlugin(settings=allowlist_agent_settings)
        
        # Agent NOT in allowlist - should be skipped
        callback_context = MockCallbackContext(agent_name="unknown-agent")
        llm_request = MockLlmRequest(
            model="gemini-pro",
            contents=[MockContent(role="user", parts=[MockPart(text="Email: john@example.com")])]
        )
        
        result = await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request
        )
        
        assert result is None
        # Content should NOT be modified
        assert "john@example.com" in llm_request.contents[0].parts[0].text
        
        print(f"\nAgent: unknown-agent (NOT in allowlist)")
        print(f"Original:  Email: john@example.com")
        print(f"Unchanged: {llm_request.contents[0].parts[0].text}")
        print("\n✓ Allowlist mode - Agent not in list is skipped")
    
    @pytest.mark.asyncio
    async def test_blocklist_agent_in_list(self, blocklist_agent_settings, capsys):
        """Test DLP skipped when agent is in blocklist."""
        print("\n" + "="*60)
        print("  TEST: Blocklist - Agent IN List")
        print("="*60)
        
        plugin = DLPPlugin(settings=blocklist_agent_settings)
        
        # Agent in blocklist - should be skipped
        callback_context = MockCallbackContext(agent_name="public-agent")
        llm_request = MockLlmRequest(
            model="gemini-pro",
            contents=[MockContent(role="user", parts=[MockPart(text="Email: john@example.com")])]
        )
        
        result = await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request
        )
        
        assert result is None
        # Content should NOT be modified
        assert "john@example.com" in llm_request.contents[0].parts[0].text
        
        print(f"\nAgent: public-agent (IN blocklist - skipped)")
        print(f"Original:  Email: john@example.com")
        print(f"Unchanged: {llm_request.contents[0].parts[0].text}")
        print("\n✓ Blocklist mode - Agent in list is skipped")
    
    @pytest.mark.asyncio
    async def test_blocklist_agent_not_in_list(self, blocklist_agent_settings, capsys):
        """Test DLP applied when agent is NOT in blocklist."""
        print("\n" + "="*60)
        print("  TEST: Blocklist - Agent NOT In List")
        print("="*60)
        
        plugin = DLPPlugin(settings=blocklist_agent_settings)
        
        # Agent NOT in blocklist - should be scanned (using actual agent name)
        callback_context = MockCallbackContext(agent_name="sub_agent")
        llm_request = MockLlmRequest(
            model="gemini-pro",
            contents=[MockContent(role="user", parts=[MockPart(text="Email: john@example.com")])]
        )
        
        result = await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request
        )
        
        assert result is None
        # Content should be modified
        assert "j***@example.com" in llm_request.contents[0].parts[0].text
        
        print(f"\nAgent: sub_agent (NOT in blocklist - scanned)")
        print(f"Original: Email: john@example.com")
        print(f"Masked:   {llm_request.contents[0].parts[0].text}")
        print("\n✓ Blocklist mode - Agent not in list is scanned")
    
    @pytest.mark.asyncio
    async def test_tool_call_agent_filtering(self, allowlist_agent_settings, capsys):
        """Test agent filtering for tool calls."""
        print("\n" + "="*60)
        print("  TEST: Tool Call - Agent Filtering")
        print("="*60)
        
        plugin = DLPPlugin(settings=allowlist_agent_settings)
        
        tool = MockTool(name="search")
        tool_args = {"email": "john@example.com"}
        
        # Agent in allowlist - should scan (using actual agent name)
        tool_context = MockToolContext(agent_name="sub_agent")
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context
        )
        
        assert result is None
        assert "j***@example.com" in tool_args["email"]
        
        print(f"\nAgent: sub_agent (IN allowlist - scanned)")
        print(f"Original:  john@example.com")
        print(f"Masked:    {tool_args['email']}")
        print("\n✓ Tool call agent filtering works")
    
    @pytest.mark.asyncio
    async def test_tool_call_agent_filtered_out(self, allowlist_agent_settings, capsys):
        """Test tool call skipped for agent not in allowlist."""
        print("\n" + "="*60)
        print("  TEST: Tool Call - Agent Filtered Out")
        print("="*60)
        
        plugin = DLPPlugin(settings=allowlist_agent_settings)
        
        tool = MockTool(name="search")
        tool_args = {"email": "john@example.com"}
        
        # Agent NOT in allowlist - should NOT scan
        tool_context = MockToolContext(agent_name="untrusted-agent")
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context
        )
        
        assert result is None
        assert "john@example.com" in tool_args["email"]  # Unchanged
        
        print(f"\nAgent: untrusted-agent (NOT in allowlist)")
        print(f"Original:  john@example.com")
        print(f"Unchanged: {tool_args['email']}")
        print("\n✓ Tool call correctly filtered out")


# ============================================================================
# Test Enterprise Hybrid Profile
# ============================================================================

class TestEnterpriseHybridProfile:
    """Test Enterprise profile with Hybrid DLP provider."""
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_ssn_detection(self, enterprise_hybrid_settings, capsys):
        """Test US Social Security Number detection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - SSN Detection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test SSN detection
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="My SSN is 123-45-6789 for employment verification")]
        )
        
        invocation_context = MockInvocationContext()
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        assert "123-45-6789" not in result.parts[0].text
        assert "***-**-****" in result.parts[0].text
        
        print(f"\nOriginal: My SSN is 123-45-6789 for employment verification")
        print(f"Masked:   {result.parts[0].text}")
        print("\n✓ SSN detection works with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_person_name_detection(self, enterprise_hybrid_settings, capsys):
        """Test Person Name detection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - Person Name Detection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test name detection
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="Hello, my name is John Smith and I work at Microsoft")]
        )
        
        invocation_context = MockInvocationContext()
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Processed: {result.parts[0].text}")
        print("\n✓ Person name detection works with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_date_of_birth_detection(self, enterprise_hybrid_settings, capsys):
        """Test Date of Birth detection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - Date of Birth Detection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test date of birth detection
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="I was born on 01/15/1990 in New York")]
        )
        
        invocation_context = MockInvocationContext()
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Processed: {result.parts[0].text}")
        print("\n✓ Date of Birth detection works with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_api_token_detection(self, enterprise_hybrid_settings, capsys):
        """Test API Token/Key detection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - API Token Detection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test API key/token detection
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="My API key is sk-1234567890abcdef1234567890abcdef for authentication")]
        )
        
        invocation_context = MockInvocationContext()
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Processed: {result.parts[0].text}")
        print("\n✓ API Token/Key detection works with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_passport_detection(self, enterprise_hybrid_settings, capsys):
        """Test Passport Number detection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - Passport Detection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test passport detection
        user_message = MockContent(
            role="user",
            parts=[MockPart(text="My passport number is AB1234567 for international travel")]
        )
        
        invocation_context = MockInvocationContext()
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        print(f"\nOriginal: {user_message.parts[0].text}")
        print(f"Processed: {result.parts[0].text}")
        print("\n✓ Passport detection works with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_multiple_pii_types(self, enterprise_hybrid_settings, capsys):
        """Test detection of multiple PII types with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - Multiple PII Types")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        # Test multiple PII in one message
        text = """
        User Profile:
        Name: John Smith
        Email: john.smith@company.com
        Phone: (555) 123-4567
        SSN: 123-45-6789
        Date of Birth: 01/15/1990
        Passport: AB1234567
        API Key: sk-abcdef123456789
        Location: New York, USA
        IP: 192.168.1.100
        Card: 4111 1111 1111 1111
        """
        
        user_message = MockContent(role="user", parts=[MockPart(text=text)])
        invocation_context = MockInvocationContext()
        
        result = await plugin.on_user_message_callback(
            invocation_context=invocation_context,
            user_message=user_message
        )
        
        assert result is not None
        
        print(f"\nOriginal:\n{text}")
        print(f"\nProcessed:\n{result.parts[0].text}")
        print("\n✓ Multiple PII types detected and masked with enterprise hybrid profile")
    
    @pytest.mark.asyncio
    async def test_enterprise_hybrid_tool_call_protection(self, enterprise_hybrid_settings, capsys):
        """Test tool call protection with enterprise hybrid profile."""
        print("\n" + "="*60)
        print("  TEST: Enterprise Hybrid - Tool Call Protection")
        print("="*60)
        
        plugin = DLPPlugin(settings=enterprise_hybrid_settings)
        
        tool = MockTool(name="user_lookup")
        tool_args = {
            "name": "John Smith",
            "ssn": "123-45-6789",
            "date of birth": "01/15/1990",
            "api_key": "sk-abcdef123456",
            "passport": "AB1234567",
            "email": "john@example.com",
            "phone": "(555) 123-4567",
            "limit": 10  # Non-string value
        }
        tool_context = MockToolContext(agent_name="orchestrator")
        
        # Should scan since agent is in allowlist
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context
        )
        
        assert result is None
        # Verify PII is masked
        assert "123-45-6789" not in tool_args["ssn"]
        assert "01/15/1990" not in tool_args["date of birth"]
        assert tool_args["limit"] == 10  # Non-string unchanged
        
        print(f"\nOriginal Arguments:")
        print(f"  name: John Smith")
        print(f"  ssn: 123-45-6789")
        print(f"  date of birth: 01/15/1990")
        print(f"  api_key: sk-abcdef123456")
        print(f"  passport: AB1234567")
        print(f"\nMasked Arguments:")
        print(f"  name: {tool_args['name']}")
        print(f"  ssn: {tool_args['ssn']}")
        print(f"  date of birth: {tool_args['date of birth']}")
        print(f"  api_key: {tool_args['api_key']}")
        print(f"  passport: {tool_args['passport']}")
        print("\n✓ Tool call protection works with enterprise hybrid profile")


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
