"""
ADK Plugin for Comprehensive LLM Telemetry

This plugin captures all LLM-related events through ADK's callback system:
- LLM calls (before/after with token usage, latency, cost)
- Agent routing decisions (orchestrator selecting subagent/workflow)
- MCP tool calls (before/after with latency, success/error)
- Error tracking for all LLM operations

Key Features:
- Correlation ID: Trace-level ID linking all spans in a request chain
- Causation ID: Parent-child relationship between spans
- Cost estimation using live pricing data
- Comprehensive error tracking

Usage:
    from telemetry_plugin import TelemetryPlugin
    
    telemetry_plugin = TelemetryPlugin()
    runner = Runner(
        app_name="MyApp",
        agent=my_agent,
        plugins=[telemetry_plugin],
    )
"""
import time
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from contextvars import ContextVar
from datetime import datetime

from google.genai import types
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from .telemetry import (
    get_tracer,
    get_meter,
    get_trace_context,
    record_llm_metrics,
    OTEL_ENABLED,
)
from .logger import get_logger

# Import custom metrics for error categorization and hooks
try:
    from .custom_metrics import (
        MetricsHooks,
        CategorizedError,
        ErrorMetrics,
        ErrorCategory,
    )
    CUSTOM_METRICS_AVAILABLE = True
except ImportError:
    CUSTOM_METRICS_AVAILABLE = False

# Context variables for tracking correlation/causation across async calls
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_causation_id: ContextVar[Optional[str]] = ContextVar("causation_id", default=None)
_current_llm_call_start: ContextVar[Optional[float]] = ContextVar("current_llm_call_start", default=None)
_current_tool_call_start: ContextVar[Optional[float]] = ContextVar("current_tool_call_start", default=None)


def get_correlation_id() -> str:
    """Get or create correlation ID for the current request chain.
    
    The correlation ID remains constant throughout the entire request lifecycle,
    linking all spans together.
    """
    corr_id = _correlation_id.get()
    if corr_id is None:
        corr_id = str(uuid.uuid4())
        _correlation_id.set(corr_id)
    return corr_id


def set_correlation_id(corr_id: str) -> None:
    """Set the correlation ID for the current context."""
    _correlation_id.set(corr_id)


def get_causation_id() -> Optional[str]:
    """Get the causation ID (parent span ID for current operation).
    
    The causation ID tracks the parent-child relationship between spans.
    """
    return _causation_id.get()


def set_causation_id(cause_id: Optional[str]) -> None:
    """Set the causation ID for the current context."""
    _causation_id.set(cause_id)


def generate_span_id() -> str:
    """Generate a unique span ID."""
    return format(uuid.uuid4().int % (2**64), "016x")


@dataclass
class LLMCallMetrics:
    """Metrics captured for a single LLM call."""
    call_id: str
    model: str
    agent_name: str
    start_time: float
    end_time: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    correlation_id: str = ""
    causation_id: Optional[str] = None
    call_type: str = "llm_generation"  # llm_generation, agent_routing, tool_decision
    cost_usd: float = 0.0


@dataclass
class ToolCallMetrics:
    """Metrics captured for a tool/MCP call."""
    call_id: str
    tool_name: str
    agent_name: str
    start_time: float
    end_time: Optional[float] = None
    latency_ms: float = 0.0
    success: bool = True
    error_message: Optional[str] = None
    correlation_id: str = ""
    causation_id: Optional[str] = None
    tool_type: str = "mcp"  # mcp, function, api
    result_size: int = 0


class TelemetryPlugin(BasePlugin):
    """
    ADK Plugin for comprehensive LLM telemetry.
    
    Captures:
    - All LLM API calls with token usage, latency, and cost
    - Agent routing decisions (which subagent/workflow to invoke)
    - MCP tool calls with latency and success/error status
    - Correlation IDs for distributed tracing
    - Causation IDs for span parent-child relationships
    
    Metrics Recorded:
    - llm.input_tokens (counter)
    - llm.output_tokens (counter)
    - llm.latency (histogram)
    - llm.errors (counter)
    - llm.cost_usd (counter)
    - llm.routing_decisions (counter)
    - tool.calls (counter)
    - tool.latency (histogram)
    - tool.errors (counter)
    """
    
    # Track active LLM calls by call_id
    _active_llm_calls: Dict[str, LLMCallMetrics] = field(default_factory=dict)
    _active_tool_calls: Dict[str, ToolCallMetrics] = field(default_factory=dict)
    
    def __init__(self, name: str = "telemetry_plugin"):
        """Initialize the telemetry plugin."""
        super().__init__(name)
        self.logger = get_logger()
        self._active_llm_calls = {}
        self._active_tool_calls = {}
        
        self.logger.section("📊 Telemetry Plugin Initialized")
        self.logger.info(f"OpenTelemetry enabled: {OTEL_ENABLED}")
        self.logger.info("Capturing: LLM calls, Agent routing, MCP tool calls, Errors")
    
    def _get_or_create_correlation_id(self, invocation_context: InvocationContext) -> str:
        """Get existing correlation ID or create from invocation context."""
        # Try to get from context variable first
        corr_id = _correlation_id.get()
        if corr_id:
            return corr_id
        
        # Create from invocation_id or generate new
        if hasattr(invocation_context, "invocation_id") and invocation_context.invocation_id:
            corr_id = f"corr-{invocation_context.invocation_id}"
        else:
            corr_id = f"corr-{uuid.uuid4()}"
        
        _correlation_id.set(corr_id)
        return corr_id
    
    # =========================================================================
    # USER MESSAGE CALLBACK
    # =========================================================================
    
    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Initialize correlation ID at the start of a request chain."""
        # Set correlation ID for this entire request chain
        corr_id = self._get_or_create_correlation_id(invocation_context)
        
        # Get current span's trace context
        trace_ctx = get_trace_context()
        parent_span_id = trace_ctx.get("span_id")
        if parent_span_id:
            set_causation_id(parent_span_id)
        
        self.logger.debug(f"User message received - Correlation ID: {corr_id}")
        
        # Create span for user message processing
        if OTEL_ENABLED:
            tracer = get_tracer()
            with tracer.start_as_current_span("user_message") as span:
                span.set_attribute("correlation_id", corr_id)
                span.set_attribute("causation_id", get_causation_id())
                span.set_attribute("invocation_id", invocation_context.invocation_id)
                span.set_attribute("user_id", invocation_context.user_id)
                span.set_attribute("session_id", invocation_context.session.id)
        
        
        # Audit log for user message - core correlation/causation tracking
        self.logger.audit("User Message Received", {
            "correlation_id": corr_id,
            "causation_id": get_causation_id(),
            "invocation_id": invocation_context.invocation_id,
            "user_id": invocation_context.user_id,
            "session_id": invocation_context.session.id,
        })
        
        return user_message  # Don't modify, just observe
    
    # =========================================================================
    # LLM CALLBACKS
    # =========================================================================
    
    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Capture LLM call start for metrics tracking."""
        call_id = generate_span_id()
        model = llm_request.model or "unknown"
        agent_name = callback_context.agent_name
        
        # Get correlation and causation IDs
        trace_ctx = get_trace_context()
        corr_id = trace_ctx.get("trace_id") or _correlation_id.get() or f"corr-{uuid.uuid4()}"
        cause_id = trace_ctx.get("span_id")
        
        # Determine call type based on agent context
        call_type = self._determine_call_type(agent_name, llm_request)
        
        # Record start time
        start_time = time.time()
        _current_llm_call_start.set(start_time)
        
        # Create metrics record
        metrics = LLMCallMetrics(
            call_id=call_id,
            model=model,
            agent_name=agent_name,
            start_time=start_time,
            correlation_id=corr_id,
            causation_id=cause_id,
            call_type=call_type,
        )
        
        self._active_llm_calls[call_id] = metrics
        
        self.logger.debug(f"LLM call started - Agent: {agent_name}, Model: {model}, Call ID: {call_id}")
        
        # Trigger custom metrics hooks
        if CUSTOM_METRICS_AVAILABLE:
            MetricsHooks.trigger_llm_start({
                "call_id": call_id,
                "model": model,
                "agent_name": agent_name,
                "call_type": call_type,
                "correlation_id": corr_id,
                "causation_id": cause_id,
                "invocation_id": callback_context.invocation_id,
            })
        
        return None  # Don't short-circuit the call
    
    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Capture LLM call completion and record metrics."""
        start_time = _current_llm_call_start.get()
        end_time = time.time()
        
        # Find the matching active call (most recent for this agent)
        call_id = None
        metrics = None
        for cid, m in list(self._active_llm_calls.items()):
            if m.agent_name == callback_context.agent_name and m.end_time is None:
                call_id = cid
                metrics = m
                break
        
        if not metrics:
            self.logger.warning(f"No matching LLM call found for agent: {callback_context.agent_name}")
            return None
        
        # Calculate latency
        latency_ms = (end_time - metrics.start_time) * 1000 if start_time else 0
        
        # Extract token usage from response
        input_tokens = 0
        output_tokens = 0
        success = True
        error_code = None
        error_message = None
        
        if llm_response:
            # Check for usage metadata
            if hasattr(llm_response, "usage_metadata") and llm_response.usage_metadata:
                usage = llm_response.usage_metadata
                input_tokens = getattr(usage, "prompt_token_count", 0) or getattr(usage, "input_tokens", 0) or 0
                output_tokens = getattr(usage, "candidates_token_count", 0) or getattr(usage, "output_tokens", 0) or 0
            
            # Check for error
            if hasattr(llm_response, "error_code") and llm_response.error_code:
                success = False
                error_code = llm_response.error_code
                error_message = getattr(llm_response, "error_message", "Unknown error")
                
                # Categorize error and record to custom metrics
                if CUSTOM_METRICS_AVAILABLE:
                    categorized = ErrorMetrics.record_and_categorize(
                        error_code=error_code,
                        error_message=error_message,
                        correlation_id=metrics.correlation_id,
                    )
        
        # Update metrics
        metrics.end_time = end_time
        metrics.latency_ms = latency_ms
        metrics.input_tokens = input_tokens
        metrics.output_tokens = output_tokens
        metrics.success = success
        metrics.error_code = error_code
        metrics.error_message = error_message
        
        # Record to OpenTelemetry
        result = record_llm_metrics(
            model=metrics.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            success=success,
        )
        metrics.cost_usd = result.get("cost_usd", 0)
        
        # Record additional metrics for call type
        self._record_call_type_metrics(metrics)
        
        # End the span
        if OTEL_ENABLED:
            tracer = get_tracer()
            span = tracer.start_span(f"llm_call.{callback_context.agent_name}", start_time=int(metrics.start_time * 1e9))
            try:
                span.set_attribute("call_id", call_id)
                span.set_attribute("correlation_id", metrics.correlation_id)
                span.set_attribute("causation_id", metrics.causation_id or "")
                span.set_attribute("latency_ms", latency_ms)
                span.set_attribute("input_tokens", input_tokens)
                span.set_attribute("output_tokens", output_tokens)
                span.set_attribute("success", success)
                span.set_attribute("cost_usd", metrics.cost_usd)
                span.set_attribute("call_type", metrics.call_type)
                
                if not success:
                    span.set_attribute("error_code", error_code or "")
                    span.set_attribute("error_message", error_message or "")
            finally:
                span.end(end_time=int(end_time * 1e9))
        
        # Log the call
        log_level = "info" if success else "warning"
        getattr(self.logger, log_level)(
            f"LLM call completed - Agent: {callback_context.agent_name}, "
            f"Model: {metrics.model}, Tokens: {input_tokens}/{output_tokens}, "
            f"Latency: {latency_ms:.1f}ms, Cost: ${metrics.cost_usd:.6f}, "
            f"Success: {success}"
        )
        
        # Audit log for LLM call
        self.logger.audit("LLM Call Completed", {
            "call_id": call_id,
            "correlation_id": metrics.correlation_id,
            "causation_id": metrics.causation_id,
            "agent_name": callback_context.agent_name,
            "model": metrics.model,
            "call_type": metrics.call_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 2),
            "cost_usd": round(metrics.cost_usd, 6),
            "success": success,
            "error_code": error_code,
            "error_message": error_message,
        })
        
        # Trigger custom metrics hooks for LLM end
        if CUSTOM_METRICS_AVAILABLE:
            MetricsHooks.trigger_llm_end({
                "call_id": call_id,
                "correlation_id": metrics.correlation_id,
                "causation_id": metrics.causation_id,
                "agent_name": callback_context.agent_name,
                "model": metrics.model,
                "call_type": metrics.call_type,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": round(latency_ms, 2),
                "cost_usd": round(metrics.cost_usd, 6),
                "success": success,
                "error_code": error_code,
                "error_message": error_message,
            })
        
        # Clean up
        if call_id in self._active_llm_calls:
            del self._active_llm_calls[call_id]
        
        return None  # Don't modify response
    
    # =========================================================================
    # TOOL CALLBACKS
    # =========================================================================
    
    async def before_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: Dict[str, Any],
        tool_context: Any,
    ) -> Optional[Dict]:
        """Capture tool/MCP call start for metrics tracking."""
        call_id = generate_span_id()
        tool_name = getattr(tool, "name", str(tool))
        agent_name = getattr(tool_context, "agent_name", "unknown")
        
        # Determine tool type
        tool_type = self._determine_tool_type(tool)
        
        # Get correlation and causation IDs
        trace_ctx = get_trace_context()
        corr_id = trace_ctx.get("trace_id") or _correlation_id.get() or f"corr-{uuid.uuid4()}"
        cause_id = trace_ctx.get("span_id")
        
        # Record start time
        start_time = time.time()
        _current_tool_call_start.set(start_time)
        
        # Create metrics record
        metrics = ToolCallMetrics(
            call_id=call_id,
            tool_name=tool_name,
            agent_name=agent_name,
            start_time=start_time,
            correlation_id=corr_id,
            causation_id=cause_id,
            tool_type=tool_type,
        )
        
        self._active_tool_calls[call_id] = metrics
        
        self.logger.debug(f"Tool call started - Tool: {tool_name}, Agent: {agent_name}, Type: {tool_type}")
        
        # Trigger custom metrics hooks for tool start
        if CUSTOM_METRICS_AVAILABLE:
            MetricsHooks.trigger_tool_start({
                "call_id": call_id,
                "tool_name": tool_name,
                "agent_name": agent_name,
                "tool_type": tool_type,
                "correlation_id": corr_id,
                "causation_id": cause_id,
            })
        
        
        return None  # Don't short-circuit the call
    
    async def after_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: Dict[str, Any],
        tool_context: Any,
        result: Dict,
    ) -> Optional[Dict]:
        """Capture tool call completion and record metrics."""
        start_time = _current_tool_call_start.get()
        end_time = time.time()
        tool_name = getattr(tool, "name", str(tool))
        agent_name = getattr(tool_context, "agent_name", "unknown")
        
        # Find the matching active call
        call_id = None
        metrics = None
        for cid, m in list(self._active_tool_calls.items()):
            if m.tool_name == tool_name and m.end_time is None:
                call_id = cid
                metrics = m
                break
        
        if not metrics:
            self.logger.warning(f"No matching tool call found for tool: {tool_name}")
            return None
        
        # Calculate latency
        latency_ms = (end_time - metrics.start_time) * 1000 if start_time else 0
        
        # Determine success and result size
        success = True
        error_message = None
        result_size = 0
        
        if result:
            # Check for error in result
            if isinstance(result, dict):
                if "error" in result or "Error" in str(result):
                    success = False
                    error_message = result.get("error") or result.get("Error")
                result_size = len(str(result))
        
        # Update metrics
        metrics.end_time = end_time
        metrics.latency_ms = latency_ms
        metrics.success = success
        metrics.error_message = error_message
        metrics.result_size = result_size
        
        # Record tool metrics
        self._record_tool_metrics(metrics)
        
        # End the span
        if OTEL_ENABLED:
            tracer = get_tracer()
            span = tracer.start_span(f"tool_call.{tool_name}", start_time=int(metrics.start_time * 1e9))
            try:
                span.set_attribute("call_id", call_id)
                span.set_attribute("correlation_id", metrics.correlation_id)
                span.set_attribute("causation_id", metrics.causation_id or "")
                span.set_attribute("latency_ms", latency_ms)
                span.set_attribute("success", success)
                span.set_attribute("tool_type", metrics.tool_type)
                span.set_attribute("result_size", result_size)
                
                # Safely capture tool arguments for deep debugging
                try:
                    safe_args = {k: v for k, v in tool_args.items() if not any(sensitive in k.lower() for sensitive in ['secret', 'password', 'key', 'token'])}
                    span.set_attribute("tool_args", str(safe_args))
                except Exception:
                    pass

                if not success:
                    span.set_attribute("error_message", error_message or "")
            finally:
                span.end(end_time=int(end_time * 1e9))
        
        # Log the call
        log_level = "info" if success else "warning"
        getattr(self.logger, log_level)(
            f"Tool call completed - Tool: {tool_name}, Agent: {agent_name}, "
            f"Latency: {latency_ms:.1f}ms, Success: {success}"
        )
        
        # Audit log for tool call - core correlation/causation tracking
        self.logger.audit("Tool Call Completed", {
            "call_id": call_id,
            "correlation_id": metrics.correlation_id,
            "causation_id": metrics.causation_id,
            "tool_name": tool_name,
            "agent_name": agent_name,
            "tool_type": metrics.tool_type,
            "latency_ms": round(latency_ms, 2),
            "success": success,
            "result_size": result_size,
            "error_message": error_message,
        })
        
        # Trigger custom metrics hooks for tool end
        if CUSTOM_METRICS_AVAILABLE:
            MetricsHooks.trigger_tool_end({
                "call_id": call_id,
                "tool_name": tool_name,
                "agent_name": agent_name,
                "tool_type": metrics.tool_type,
                "correlation_id": metrics.correlation_id,
                "causation_id": metrics.causation_id,
                "latency_ms": round(latency_ms, 2),
                "success": success,
                "result_size": result_size,
                "error_message": error_message,
            })
        
        
        # Clean up
        if call_id in self._active_tool_calls:
            del self._active_tool_calls[call_id]
        
        return None  # Don't modify result
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _determine_call_type(self, agent_name: str, llm_request: LlmRequest) -> str:
        """Determine the type of LLM call based on context.
        
        Types:
        - llm_generation: Standard content generation
        - agent_routing: Orchestrator deciding which subagent to call
        - tool_decision: Agent deciding which tool to use
        - workflow_routing: Agent deciding which workflow to trigger
        """
        # Check if this is an orchestrator making a routing decision
        if "orchestrator" in agent_name.lower():
            # Check the request content for routing keywords
            if llm_request.contents:
                for content in llm_request.contents:
                    if content and content.parts:
                        for part in content.parts:
                            if hasattr(part, "text") and part.text:
                                text_lower = part.text.lower()
                                if any(kw in text_lower for kw in ["delegate", "transfer", "route", "subagent", "workflow"]):
                                    return "agent_routing"
            return "agent_routing"  # Default for orchestrator
        
        # Check if agent is making a tool decision
        tools = getattr(llm_request, "tools", None) or getattr(llm_request, "config", None)
        if tools:
            # Check for tools in config if tools is a config object
            tools_list = getattr(tools, "tools", None) if hasattr(tools, "tools") else tools
            if tools_list and len(tools_list) > 0:
                return "tool_decision"
        
        return "llm_generation"
    
    def _determine_tool_type(self, tool: Any) -> str:
        """Determine the type of tool call.
        
        Types:
        - mcp: Model Context Protocol tool
        - function: Python function tool
        - api: External API call tool
        """
        tool_name = getattr(tool, "name", str(tool)).lower()
        
        if "mcp" in tool_name or "model_context" in tool_name:
            return "mcp"
        elif "api" in tool_name or "http" in tool_name or "request" in tool_name:
            return "api"
        else:
            return "function"
    
    def _record_call_type_metrics(self, metrics: LLMCallMetrics) -> None:
        """Record additional metrics based on call type."""
        if not OTEL_ENABLED:
            return
        
        meter = get_meter()
        
        # Routing decisions counter
        if metrics.call_type in ("agent_routing", "workflow_routing"):
            routing_counter = meter.create_counter(
                "llm.routing_decisions",
                unit="decisions",
                description="Number of agent/workflow routing decisions",
            )
            attrs = {
                "agent_name": metrics.agent_name,
                "call_type": metrics.call_type,
                "correlation_id": metrics.correlation_id,
            }
            routing_counter.add(1, attrs)
    
    def _record_tool_metrics(self, metrics: ToolCallMetrics) -> None:
        """Record tool call metrics to OpenTelemetry."""
        if not OTEL_ENABLED:
            return
        
        meter = get_meter()
        
        # Tool call counter
        call_counter = meter.create_counter(
            "tool.calls",
            unit="calls",
            description="Number of tool/MCP calls",
        )
        
        # Tool latency histogram
        latency_hist = meter.create_histogram(
            "tool.latency",
            unit="ms",
            description="Tool call latency",
        )
        
        # Tool error counter
        error_counter = meter.create_counter(
            "tool.errors",
            unit="errors",
            description="Number of tool call errors",
        )
        
        # Record metrics
        attrs = {
            "tool_name": metrics.tool_name,
            "agent_name": metrics.agent_name,
            "tool_type": metrics.tool_type,
            "correlation_id": metrics.correlation_id,
        }
        
        call_counter.add(1, attrs)
        latency_hist.record(metrics.latency_ms, attrs)
        
        if not metrics.success:
            error_counter.add(1, attrs)


def create_telemetry_plugin() -> TelemetryPlugin:
    """Convenience function to create a TelemetryPlugin instance."""
    return TelemetryPlugin()
