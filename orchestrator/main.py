"""Orchestrator agent for ADK with OpenTelemetry tracing."""
import os
from google.adk.agents import LlmAgent, Agent
from google.adk.agents.invocation_context import InvocationContext
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# OpenTelemetry imports for tracing
try:
    from opentelemetry import trace
    from opentelemetry.trace.status import Status, StatusCode
    _TRACER = trace.get_tracer("orchestrator-agent")
    TRACING_AVAILABLE = True
except ImportError:
    _TRACER = None
    TRACING_AVAILABLE = False


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


MODEL  = _env("MODEL", "gemini-2.5-flash")

_INSTRUCTION = """
You are the Orchestrator, the primary point of contact for all user queries.

Your responsibilities:
1. Greet the user warmly on the first message.
2. For EVERY user query, delegate it to the sub_agent to handle.
3. Wait for the sub_agent's response, then summarize it into approximately 100 words.
4. NEVER answer any query directly - always delegate to sub_agent first.
5. Your only job is to receive the user query, delegate it, and provide a concise 100-word summary of the sub_agent's response back to the user.

IMPORTANT:
- Do NOT use any tools yourself.
- Do NOT answer directly.
- Always delegate ALL queries to sub_agent.
- Keep your final response to approximately 100 words.
"""


class OrchestratorAgent:
    """Orchestrator agent that coordinates with sub agents."""

    def __init__(self, sub_agents=None):
        """Initialize the orchestrator agent with Vertex AI."""
        self.agent = LlmAgent(
            name="orchestrator",
            model=MODEL,
            description="Main orchestrator agent that coordinates tasks and delegates to sub agents.",
            instruction=_INSTRUCTION.strip(),
            # disallow_transfer_to_peers=True,
            # disallow_transfer_to_parent=True,
            sub_agents=sub_agents or []
        )

    async def invoke(self, context: InvocationContext):
        """Invoke the orchestrator agent with OpenTelemetry tracing."""
        if not TRACING_AVAILABLE:
            return await self.agent.invoke(context)
        
        with _TRACER.start_as_current_span("orchestrator.invoke") as span:
            span.set_attribute("agent.name", "orchestrator")
            span.set_attribute("agent.model", self.agent.model if hasattr(self.agent, 'model') else MODEL)
            
            try:
                result = await self.agent.invoke(context)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
    
