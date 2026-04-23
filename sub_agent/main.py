"""Sub agent for specialized tasks with OpenTelemetry tracing."""

import os

from google.adk.agents import LlmAgent, Agent
from google.adk.agents.invocation_context import InvocationContext
#from google.adk.tools import GoogleSearchTool
from pathlib import Path
from dotenv import load_dotenv
from adk_web_api.telemetry import trace_agent_invocation
from adk_web_api.custom_metrics import with_retry

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


MODEL  = _env("MODEL", "gemini-2.5-flash")

_INSTRUCTION = """
You are the SubAgent, a specialized resolver that handles ANY query delegated from the Orchestrator.

Your responsibilities:
1. Accept queries on ANY topic - company information, general knowledge, fact-checking, calculations, advice, etc.
2. Provide comprehensive, accurate, and helpful responses based on your knowledge.
3. If you need current information, use the google_search tool to get up-to-date data.
4. NEVER delegate to other agents - you must provide the complete answer yourself.
5. Give clear, well-structured responses.

For Company-Related Queries:
If the query is about a company, cover these key areas where relevant:
  - Company Overview (name, headquarters, founded, industry, employee count)
  - Financial Metrics (revenue, growth, market cap, key indicators)
  - Market Position (market share, competitors, advantages, ranking)
  - Products & Services (offerings, recent launches, target segments)
  - Performance Metrics (customer satisfaction, retention, R&D, patents)
  - Strategic Information (M&A, partnerships, growth strategy, ESG initiatives)
  - Industry Trends (market adaptation, supply chain, compliance)

For General/Other Queries:
Provide accurate, helpful information using your knowledge base or the google_search tool.
Keep responses focused and relevant to the user's question.

Guidelines:
- Always be accurate and cite approximate data years when available.
- Provide context and comparisons where relevant.
- Be balanced in your assessment.
- IMPORTANT: DO NOT delegate this query to any other agent.
- Provide the complete answer yourself.
"""


class SubAgent:
    """Sub agent that handles specialized tasks for the orchestrator."""

    def __init__(self):
        """Initialize the sub agent with Vertex AI."""
        self.agent = LlmAgent(
            name="sub_agent",
            model=MODEL,
            description="Specialized sub agent for handling any queries delegated from orchestrator.",
            instruction=_INSTRUCTION.strip(),
            disallow_transfer_to_peers=True,  # Prevent delegation to other agents
            disallow_transfer_to_parent=True,  # Prevent delegation back to orchestrator
            #tools=[GoogleSearchTool()]
        )

    @trace_agent_invocation(agent_name="sub_agent")
    @with_retry(max_retries=3)
    async def invoke(self, context: InvocationContext):
        """Invoke the sub agent."""
        return await self.agent.invoke(context)
