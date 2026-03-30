"""ADK Plugin for PII/Sensitive Data Masking"""
import re
from typing import Optional

from google.genai import types
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

# Import the verbose logger
from .logger import get_logger


class PIIMaskingPlugin(BasePlugin):
    """
    ADK Plugin that automatically masks PII/sensitive data in all LLM requests
    and responses. This applies uniformly to all agents and agent delegation paths.
    
    This plugin intercepts:
    - User messages before processing
    - LLM requests before sending to model (covers all context including delegation)
    - LLM responses after receiving from model
    
    Example:
        >>> from google.adk.runners import Runner
        >>> runner = Runner(
        ...     app_name="MyApp",
        ...     agent=my_agent,
        ...     session_service=InMemorySessionService(),
        ...     plugins=[PIIMaskingPlugin()],
        ... )
    """
    
    def __init__(self, name: str = "pii_masking_plugin"):
        """Initialize the PII masking plugin."""
        super().__init__(name)
        self.patterns = {
            # Email: user@domain.com -> u***@domain.com
            'email': (
                re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
                lambda m: f"{m.group(0)[0]}***@{m.group(0).split('@')[1]}"
            ),
            
            # Phone: (555) 123-4567 -> (***) ***-****
            'phone': (
                re.compile(r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
                lambda m: '(***) ***-****'
            ),
            
            # SSN: 123-45-6789 -> ***-**-****
            'ssn': (
                re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
                lambda m: '***-**-****'
            ),
            
            # Credit Card: 4111 1111 1111 1111 -> **** **** **** ****
            'credit_card': (
                re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b'),
                lambda m: '**** **** **** ****'  # Always return a standard 4-block mask
            ),
            
            # IP Address: 192.168.1.1 -> ***.***.**.**
            'ip': (
                re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
                lambda m: re.sub(r'\d{1,3}', '***', m.group(0))
            ),
            
            # Generic tokens/API keys: alphanumeric strings >= 20 chars
            'token': (
                re.compile(r'\b[A-Za-z0-9_-]{20,}\b'),
                lambda m: f"{m.group(0)[:8]}...***"
            ),
        }
    
    def _mask_text(self, text: str) -> str:
        """Apply all PII masking patterns to the given text."""
        if not text:
            return text
        
        logger = get_logger()
        logger.debug(f"Starting PII masking for text of length: {len(text)}")
        logger.indent()
        
        original_text = text
        masked_text = text
        detections = []
        
        for pattern_name, (pattern, replacer) in self.patterns.items():
            # Find all matches for this pattern
            matches = pattern.findall(masked_text)
            if matches:
                detections.extend([(pattern_name, match) for match in matches])
                logger.debug(f"Pattern '{pattern_name}' detected {len(matches)} instance(s)")
            masked_text = pattern.sub(replacer, masked_text)
        
        logger.dedent()
        
        if detections:
            logger.info(f"PII masking completed. Found {len(detections)} PII instance(s)", details=detections)
            logger.before_after("PII Masking Result", original_text, masked_text, changed=True)
        else:
            logger.debug("No PII detected in text")
        
        return masked_text
    
    def _mask_content(self, content: types.Content) -> types.Content:
        """Mask PII in all text parts of a Content object."""
        logger = get_logger()
        
        if not content or not content.parts:
            return content
        
        logger.debug(f"Masking PII in content with {len(content.parts)} part(s)")
        
        # Create a new content with masked text parts
        masked_parts = []
        for i, part in enumerate(content.parts):
            if part.text:
                logger.debug(f"Processing part {i + 1}/{len(content.parts)} - Text length: {len(part.text)}")
                # Mask the text
                masked_text = self._mask_text(part.text)
                if masked_text != part.text:
                    logger.debug(f"Part {i + 1}: PII found and masked")
                    # Create a new Part with masked text
                    masked_parts.append(types.Part(text=masked_text))
                else:
                    logger.debug(f"Part {i + 1}: No PII found")
                    # Use original if no change
                    masked_parts.append(part)
            else:
                logger.debug(f"Part {i + 1}: Non-text part (skipping)")
                # Keep non-text parts (function calls, etc.) unchanged
                masked_parts.append(part)
        
        # Return a new Content with masked parts if needed
        if any(p.text for p in masked_parts if p.text):
            # Check if any text was actually masked
            original_texts = [p.text for p in content.parts if p.text]
            masked_texts = [p.text for p in masked_parts if p.text]
            
            if original_texts != masked_texts:
                logger.success("Content masking completed - PII detected and masked")
                return types.Content(role=content.role, parts=masked_parts)
        
        logger.debug("No PII detected in content - returning unchanged")
        return content
    
    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Mask PII in incoming user messages before processing."""
        logger = get_logger()
        logger.section(f"User Message Processing - Invocation: {invocation_context.invocation_id}")
        logger.info(f"User ID: {invocation_context.user_id}")
        logger.info(f"Session ID: {invocation_context.session.id}")
        logger.indent()
        
        logger.step("Incoming User Message Received")
        
        original_text = ''.join(p.text for p in user_message.parts if p.text) if user_message.parts else ""
        logger.debug(f"Original message: {original_text[:200]}{'...' if len(original_text) > 200 else ''}")
        
        masked_content = self._mask_content(user_message)
        
        masked_text = ''.join(p.text for p in masked_content.parts if p.text) if masked_content.parts else ""
        
        # Log if PII was detected and masked
        if masked_content != user_message:
            logger.audit("PII Masking - User Message", {
                "invocation_id": invocation_context.invocation_id,
                "user_id": invocation_context.user_id,
                "original_length": len(original_text),
                "masked_length": len(masked_text),
                "changed": True
            })
            logger.success("User message masked successfully")
            logger.before_after("User Message", original_text, masked_text, changed=True)
        else:
            logger.info("No PII detected in user message - proceeding unchanged")
            logger.audit("PII Masking - User Message", {
                "invocation_id": invocation_context.invocation_id,
                "user_id": invocation_context.user_id,
                "original_length": len(original_text),
                "changed": False
            })
        
        logger.dedent()
        return masked_content
    
    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Mask PII in LLM request before sending to model.
        
        This is critical - it masks ALL context including:
        - Current user message
        - Conversation history
        - Delegated agent communications
        """
        logger = get_logger()
        logger.flow(callback_context.agent_name, "LLM Request PII Masking")
        logger.step("Before LLM Call - PII Masking")
        logger.indent()
        
        logger.debug(f"Model: {llm_request.model}")
        logger.debug(f"Number of contents in request: {len(llm_request.contents)}")
        
        # Mask PII in all request contents
        if llm_request.contents:
            logger.info("Processing LLM request contents for PII")
            logger.indent()
            
            masked_contents = []
            content_changed = False
            
            for i, content in enumerate(llm_request.contents):
                logger.debug(f"Processing content {i + 1}/{len(llm_request.contents)} - Role: {content.role}")
                masked_content = self._mask_content(content)
                masked_contents.append(masked_content)
                
                # Check if this content was modified
                orig_text = ''.join(p.text for p in content.parts if p.text)
                masked_text = ''.join(p.text for p in masked_content.parts if p.text)
                if orig_text != masked_text:
                    content_changed = True
                    logger.debug(f"Content {i + 1}: PII detected and masked")
            
            logger.dedent()
            
            if content_changed:
                logger.success("LLM request PII masking completed")
                logger.audit("LLM Request PII Masking", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "model": llm_request.model,
                    "contents_count": len(llm_request.contents),
                    "changed": True
                })
                llm_request.contents = masked_contents
            else:
                logger.info("No PII detected in LLM request")
                logger.audit("LLM Request PII Masking", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "model": llm_request.model,
                    "contents_count": len(llm_request.contents),
                    "changed": False
                })
        else:
            logger.warning("LLM request has no contents to mask")
        
        logger.dedent()
        
        # Return None to proceed normally
        return None
    
    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Mask PII in LLM response after receiving from model."""
        logger = get_logger()
        logger.flow("LLM Response", "PII Masking")
        logger.step("After LLM Call - PII Masking")
        logger.indent()
        
        if llm_response.content:
            logger.debug(f"LLM response content present - Role: {llm_response.content.role}")
            
            # Log before masking
            original_text = ''.join(p.text for p in llm_response.content.parts if p.text)
            logger.debug(f"Original response: {original_text[:200]}{'...' if len(original_text) > 200 else ''}")
            
            masked_content = self._mask_content(llm_response.content)
            
            # Log after masking
            masked_text = ''.join(p.text for p in masked_content.parts if p.text)
            
            if masked_content != llm_response.content:
                logger.success("LLM response PII masking completed")
                logger.audit("LLM Response PII Masking", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "original_length": len(original_text),
                    "masked_length": len(masked_text),
                    "changed": True
                })
                logger.before_after("LLM Response", original_text, masked_text, changed=True)
                llm_response.content = masked_content
            else:
                logger.info("No PII detected in LLM response")
                logger.audit("LLM Response PII Masking", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "original_length": len(original_text),
                    "changed": False
                })
        else:
            logger.warning("LLM response has no content to mask")
            if llm_response.error_code:
                logger.error("LLM call failed with error", details={
                    "error_code": llm_response.error_code,
                    "error_message": llm_response.error_message
                })
        
        logger.dedent()
        
        # Return None to proceed normally with masked response
        return None


# Convenience function for easy usage
def create_pii_masking_plugin(name: str = "pii_masking_plugin") -> PIIMaskingPlugin:
    """Create a PII masking plugin with the given name."""
    return PIIMaskingPlugin(name=name)