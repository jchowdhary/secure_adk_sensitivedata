import pytest
from unittest.mock import MagicMock
from google.genai import types

# Standard ADK imports
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.agents.callback_context import CallbackContext

# Import your plugin
from .pii_masking_plugin import PIIMaskingPlugin

@pytest.fixture
def plugin():
    return PIIMaskingPlugin()

@pytest.mark.asyncio
async def test_ip_and_token_masking_fixed(plugin):
    """Verifies technical IDs are scrubbed and matches actual regex output."""
    user_msg = types.Content(
        role="user",
        parts=[types.Part(text="Server 10.0.0.1 and key AIzaSyB-12345678901234567890")]
    )
    
    # FIXED: Using keyword arguments
    result = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=user_msg
    )
    
    text = result.parts[0].text
    assert "***.***.***.***" in text
    assert "AIzaSyB-..." in text # Matches the 'token' lambda: f"{m.group(0)[:8]}...***"

@pytest.mark.asyncio
async def test_credit_card_masking_variants(plugin):
    """Tests that both dashed and spaced credit cards are masked to the same format."""
    
    # Test Dashed
    msg_dash = types.Content(role="user", parts=[types.Part(text="Card: 4111-2222-3333-4444")])
    res_dash = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=msg_dash
    )
    assert "**** **** **** ****" in res_dash.parts[0].text
    
    # Test Spaced
    msg_space = types.Content(role="user", parts=[types.Part(text="Card: 4111 2222 3333 4444")])
    res_space = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=msg_space
    )
    assert "**** **** **** ****" in res_space.parts[0].text

@pytest.mark.asyncio
async def test_ssn_masking(plugin):
    """Ensures government IDs are masked."""
    user_msg = types.Content(
        role="user",
        parts=[types.Part(text="SSN is 123-45-6789")]
    )
    # FIXED: Using keyword arguments
    result = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=user_msg
    )
    assert "***-**-****" in result.parts[0].text

@pytest.mark.asyncio
async def test_empty_content_handling(plugin):
    """Ensures the plugin doesn't crash on empty or non-text parts."""
    # Test with no parts
    empty_content = types.Content(role="user", parts=[])
    result = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=empty_content
    )
    assert len(result.parts) == 0

    # Test with a non-text part (e.g. function call result)
    # Note: Using keyword arguments here too
    content_with_func = types.Content(role="user", parts=[types.Part(text=None)])
    result = await plugin.on_user_message_callback(
        invocation_context=MagicMock(), 
        user_message=content_with_func
    )
    assert result.parts[0].text is None

@pytest.mark.asyncio
async def test_before_model_callback_masking(plugin):
    """Tests the critical hook that masks context before it hits the LLM."""
    request = LlmRequest(
        contents=[
            types.Content(role="user", parts=[types.Part(text="Email me: test@test.com")])
        ]
    )
    
    # This hook uses callback_context and llm_request as keyword args
    await plugin.before_model_callback(
        callback_context=MagicMock(),
        llm_request=request
    )
    
    assert "t***@test.com" in request.contents[0].parts[0].text