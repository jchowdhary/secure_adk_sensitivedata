"""
ADK Plugin for Data Loss Prevention (DLP)

This plugin provides comprehensive DLP capabilities integrated with ADK's
plugin system. It supports:
- Multiple detection providers (regex, Google Cloud DLP, hybrid)
- Configurable info types and actions
- Scope control (user messages, LLM calls, tool calls)
- Tool call scanning
"""
from typing import Optional, Dict, Any, List

from google.genai import types
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from .dlp_config import DLPSettings, DLPProfiles
from .dlp_service import DLPService
from .logger import get_logger

# Import Governance Metrics
try:
    from .custom_metrics import GovernanceAndRiskMetrics
    CUSTOM_METRICS_AVAILABLE = True
except ImportError:
    CUSTOM_METRICS_AVAILABLE = False


class DLPPlugin(BasePlugin):
    """
    ADK Plugin for Data Loss Prevention.
    
    This plugin intercepts and processes all data flows through ADK:
    - User messages before processing
    - LLM requests before sending to model
    - LLM responses after receiving from model
    - Tool calls before execution
    - Tool results after execution
    
    Features:
    - Configurable info types (what to detect)
    - Multiple detection providers (regex, Google Cloud DLP, hybrid)
    - Configurable actions (mask, redact, replace, hash, alert)
    - Scope control (what to scan)
    - Comprehensive audit logging
    
    Example:
        >>> from google.adk.runners import Runner
        >>> from dlp_config import DLPProfiles
        >>> 
        >>> # Use predefined profile
        >>> dlp_settings = DLPProfiles.standard()
        >>> dlp_plugin = DLPPlugin(settings=dlp_settings)
        >>> 
        >>> runner = Runner(
        ...     app_name="MyApp",
        ...     agent=my_agent,
        ...     session_service=InMemorySessionService(),
        ...     plugins=[dlp_plugin],
        ... )
    """
    
    def __init__(
        self, 
        name: str = "dlp_plugin",
        settings: Optional[DLPSettings] = None
    ):
        """
        Initialize DLP plugin.
        
        Args:
            name: Plugin name for identification
            settings: DLP settings configuration. If not provided, uses default.
        """
        super().__init__(name)
        self.settings = settings or DLPSettings.from_env()
        self.dlp_service = DLPService(self.settings)
        self.logger = get_logger()
        
        self.logger.section(f"🔐 DLP Plugin Initialized")
        self.logger.info(f"Provider: {self.settings.provider.value}")
        self.logger.info(f"Action: {self.settings.action.value}")
        self.logger.info(f"Info types: {', '.join(self.settings.info_types[:5])}{'...' if len(self.settings.info_types) > 5 else ''}")
        self.logger.debug(f"Scan scopes: user={self.settings.scan_user_messages}, llm_req={self.settings.scan_llm_requests}, llm_resp={self.settings.scan_llm_responses}, tools={self.settings.scan_tool_calls}")
        self.logger.debug(f"Agent filter: mode={self.settings.agent_filter_mode.value}, enabled={self.settings.enabled_agents}, disabled={self.settings.disabled_agents}")
    
    def _process_content(self, content: types.Content, context: str) -> types.Content:
        """Process content object for DLP."""
        if not content or not content.parts:
            return content
        
        self.logger.debug(f"Processing content with {len(content.parts)} part(s) - Context: {context}")
        self.logger.indent()
        
        # Track if any modifications were made
        modified_parts = []
        all_findings = []
        
        for i, part in enumerate(content.parts):
            if part.text:
                # Scan text for PII
                result = self.dlp_service.scan(part.text, context=f"{context}.part{i}")
                
                if result.was_modified:
                    modified_parts.append(types.Part(text=result.processed_text))
                    all_findings.extend(result.findings)
                else:
                    modified_parts.append(part)
            else:
                # Keep non-text parts unchanged
                modified_parts.append(part)
        
        self.logger.dedent()
        
        # Return modified content if changes were made
        if all_findings:
            self.logger.success(f"Content processed - {len(all_findings)} finding(s) in {context}")
            self.logger.audit(f"DLP Content Processing - {context}", {
                "findings_count": len(all_findings),
                "info_types": list(set(f.info_type for f in all_findings))
            })
            
            # Record Custom Governance Metric
            if CUSTOM_METRICS_AVAILABLE:
                for unique_info_type in set(f.info_type for f in all_findings):
                    GovernanceAndRiskMetrics.record_policy_event(
                        policy_type="pii_detected",
                        action_taken=self.settings.action.value,
                        trigger_reason=unique_info_type,
                        use_case=context
                    )
            return types.Content(role=content.role, parts=modified_parts)
        
        return content
    
    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Process user message for DLP."""
        if not self.settings.scan_user_messages:
            return user_message
        
        self.logger.section(f"📨 DLP: User Message - Invocation: {invocation_context.invocation_id}")
        self.logger.info(f"User ID: {invocation_context.user_id}")
        self.logger.info(f"Session ID: {invocation_context.session.id}")
        self.logger.indent()
        
        self.logger.step("Scanning user message for sensitive data")
        
        processed_content = self._process_content(user_message, "user_message")
        
        self.logger.dedent()
        return processed_content
    
    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Process LLM request for DLP."""
        if not self.settings.scan_llm_requests:
            return None
        
        # Check if this agent should be scanned
        if not self.settings.should_scan_agent(callback_context.agent_name):
            self.logger.debug(f"Skipping DLP for agent: {callback_context.agent_name} (not in filter scope)")
            return None
        
        self.logger.flow(callback_context.agent_name, "DLP: LLM Request Scanning")
        self.logger.step("Before LLM Call - DLP Scanning")
        self.logger.indent()
        
        self.logger.debug(f"Model: {llm_request.model}")
        self.logger.debug(f"Number of contents: {len(llm_request.contents) if llm_request.contents else 0}")
        
        if llm_request.contents:
            self.logger.info("Processing LLM request contents for DLP")
            self.logger.indent()
            
            total_findings = 0
            for i, content in enumerate(llm_request.contents):
                processed_content = self._process_content(content, f"llm_request.content{i}")
                
                # Check if content was modified
                if processed_content != content:
                    llm_request.contents[i] = processed_content
                    self.logger.debug(f"Content {i} modified")
                
                # Count findings
                if processed_content.parts:
                    for part in processed_content.parts:
                        if part.text and part.text != content.parts[0].text if content.parts else True:
                            total_findings += 1
            
            self.logger.dedent()
            
            if total_findings > 0:
                self.logger.success(f"LLM request DLP completed - {total_findings} modification(s)")
                self.logger.audit("DLP: LLM Request Processing", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "model": llm_request.model,
                    "modifications_count": total_findings
                })
            else:
                self.logger.info("No sensitive data detected in LLM request")
        else:
            self.logger.warning("LLM request has no contents to scan")
        
        self.logger.dedent()
        return None
    
    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Process LLM response for DLP."""
        if not self.settings.scan_llm_responses:
            return None
        
        # Check if this agent should be scanned
        if not self.settings.should_scan_agent(callback_context.agent_name):
            self.logger.debug(f"Skipping DLP for agent: {callback_context.agent_name} (not in filter scope)")
            return None
        
        self.logger.flow("LLM Response", "DLP: Response Scanning")
        self.logger.step("After LLM Call - DLP Scanning")
        self.logger.indent()
        
        if llm_response.content:
            processed_content = self._process_content(llm_response.content, "llm_response")
            
            if processed_content != llm_response.content:
                llm_response.content = processed_content
                self.logger.success("LLM response DLP completed")
                self.logger.audit("DLP: LLM Response Processing", {
                    "agent_name": callback_context.agent_name,
                    "invocation_id": callback_context.invocation_id,
                    "modified": True
                })
            else:
                self.logger.info("No sensitive data detected in LLM response")
        else:
            if llm_response.error_code:
                self.logger.error("LLM call failed", details={
                    "error_code": llm_response.error_code,
                    "error_message": llm_response.error_message
                })
            else:
                self.logger.warning("LLM response has no content to scan")
        
        self.logger.dedent()
        return None
    
    async def before_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: Dict[str, Any],
        tool_context: Any,
    ) -> Optional[Dict]:
        """Process tool call arguments for DLP."""
        if not self.settings.scan_tool_calls:
            return None
        
        if not tool_args or not isinstance(tool_args, dict):
            return None
        
        # Check if this agent should be scanned
        if not self.settings.should_scan_agent(tool_context.agent_name):
            self.logger.debug(f"Skipping DLP for agent: {tool_context.agent_name} (not in filter scope)")
            return None
        
        self.logger.flow(tool_context.agent_name, f"DLP: Tool Call - {tool.name}")
        self.logger.step(f"Before Tool Call - DLP Scanning")
        self.logger.indent()
        
        self.logger.debug(f"Tool: {tool.name}")
        self.logger.debug(f"Arguments: {list(tool_args.keys())}")
        
        # Scan tool arguments
        masked_args, findings = self.dlp_service.scan_tool_call(tool.name, tool_args)
        
        if findings:
            self.logger.success(f"Tool call DLP completed - {len(findings)} finding(s)")
            self.logger.audit("DLP: Tool Call Processing", {
                "tool_name": tool.name,
                "agent_name": tool_context.agent_name,
                "findings_count": len(findings),
                "info_types": list(set(f.info_type for f in findings))
            })
            
            # Record Custom Governance Metric
            if CUSTOM_METRICS_AVAILABLE:
                for unique_info_type in set(f.info_type for f in findings):
                    GovernanceAndRiskMetrics.record_policy_event(
                        policy_type="pii_detected",
                        action_taken=self.settings.action.value,
                        trigger_reason=unique_info_type,
                        use_case=f"tool_call:{tool.name}"
                    )
            
            # Return masked args to short-circuit the original call
            # This is the only way to modify tool args in ADK
            # We need to call the tool ourselves with masked args
            self.logger.debug("Executing tool with masked arguments")
            self.logger.dedent()
            
            # Let the tool execute with masked args
            # We'll return None to let the original tool execute with our modifications
            # ADK will use the tool_args we modified if we return None
            
            # Actually, we need to modify tool_args in place
            # Update the original dict
            tool_args.update(masked_args)
            
            return None  # Return None to proceed with modified args
        else:
            self.logger.info("No sensitive data detected in tool call")
        
        self.logger.dedent()
        return None
    
    async def after_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: Dict[str, Any],
        tool_context: Any,
        result: Dict,
    ) -> Optional[Dict]:
        """Process tool call results for DLP."""
        if not self.settings.scan_tool_results:
            return None
        
        if not result or not isinstance(result, dict):
            return None
        
        # Check if this agent should be scanned
        if not self.settings.should_scan_agent(tool_context.agent_name):
            self.logger.debug(f"Skipping DLP for agent: {tool_context.agent_name} (not in filter scope)")
            return None
        
        self.logger.flow(f"Tool Result - {tool.name}", "DLP: Result Scanning")
        self.logger.step("After Tool Call - DLP Scanning")
        self.logger.indent()
        
        # Scan tool result (typically a dict with string values)
        masked_result = {}
        findings = []
        
        for key, value in result.items():
            if isinstance(value, str):
                scan_result = self.dlp_service.scan(value, context=f"tool_result:{tool.name}.{key}")
                masked_result[key] = scan_result.processed_text
                findings.extend(scan_result.findings)
            elif isinstance(value, dict):
                # Recursively scan nested dicts
                nested_masked, nested_findings = self._scan_dict(value, f"tool_result:{tool.name}.{key}")
                masked_result[key] = nested_masked
                findings.extend(nested_findings)
            else:
                masked_result[key] = value
        
        if findings:
            self.logger.success(f"Tool result DLP completed - {len(findings)} finding(s)")
            self.logger.audit("DLP: Tool Result Processing", {
                "tool_name": tool.name,
                "agent_name": tool_context.agent_name,
                "findings_count": len(findings),
                "info_types": list(set(f.info_type for f in findings))
            })
            
            # Record Custom Governance Metric
            if CUSTOM_METRICS_AVAILABLE:
                for unique_info_type in set(f.info_type for f in findings):
                    GovernanceAndRiskMetrics.record_policy_event(
                        policy_type="pii_detected",
                        action_taken=self.settings.action.value,
                        trigger_reason=unique_info_type,
                        use_case=f"tool_result:{tool.name}"
                    )
            self.logger.dedent()
            return masked_result
        else:
            self.logger.info("No sensitive data detected in tool result")
        
        self.logger.dedent()
        return None
    
    def _scan_dict(self, data: Dict[str, Any], context: str) -> tuple[Dict[str, Any], List]:
        """Recursively scan a dictionary for PII."""
        masked_data = {}
        findings = []
        
        for key, value in data.items():
            if isinstance(value, str):
                result = self.dlp_service.scan(value, context=f"{context}.{key}")
                masked_data[key] = result.processed_text
                findings.extend(result.findings)
            elif isinstance(value, dict):
                nested_masked, nested_findings = self._scan_dict(value, f"{context}.{key}")
                masked_data[key] = nested_masked
                findings.extend(nested_findings)
            else:
                masked_data[key] = value
        
        return masked_data, findings


def create_dlp_plugin(
    profile: str = "basic",
    settings: Optional[DLPSettings] = None
) -> DLPPlugin:
    """
    Convenience function to create DLP plugin.
    
    Args:
        profile: Predefined profile name ("basic", "standard", "enterprise", "hybrid")
        settings: Custom settings (overrides profile)
    
    Returns:
        Configured DLPPlugin instance
    """
    if settings:
        return DLPPlugin(settings=settings)
    
    # Use predefined profile
    profile_map = {
        "basic": DLPProfiles.basic,
        "standard": DLPProfiles.standard,
        "enterprise": DLPProfiles.enterprise,
        "hybrid": DLPProfiles.hybrid,
    }
    
    profile_func = profile_map.get(profile, DLPProfiles.basic)
    return DLPPlugin(settings=profile_func())