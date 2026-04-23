"""Orchestrator agent for ADK with OpenTelemetry tracing."""
import os
from google.adk.agents import LlmAgent, Agent
from google.adk.agents.invocation_context import InvocationContext
from pathlib import Path
from dotenv import load_dotenv
from adk_web_api.telemetry import trace_agent_invocation
from adk_web_api.custom_metrics import with_retry

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

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

    @trace_agent_invocation(agent_name="orchestrator")
    @with_retry(max_retries=1)
    async def invoke(self, context: InvocationContext):
        """Invoke the orchestrator agent."""
        return await self.agent.invoke(context)
    
