"""FastAPI entry point for ADK agents."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# SECRET MANAGER INTEGRATION (Commented out - see SECRET_MANAGER_GUIDE.md)
# ============================================================================
# To enable Secret Manager for Cloud Run deployments:
# 1. Uncomment the code below
# 2. Set env vars: LOAD_SECRETS_FROM_SECRET_MANAGER=true, SECRETS_TO_LOAD=dlp-config
# 3. See SECRET_MANAGER_GUIDE.md for complete setup instructions
# ============================================================================

# # Set this env var to enable Secret Manager loading
# # In Cloud Run, set: LOAD_SECRETS_FROM_SECRET_MANAGER=true
# if os.getenv("LOAD_SECRETS_FROM_SECRET_MANAGER", "false").lower() == "true":
#     try:
#         from .secret_manager import load_secrets_at_startup, load_dlp_config_from_secret
#         
#         # List of secrets to load (comma-separated in env var or list below)
#         secrets_to_load_str = os.getenv("SECRETS_TO_LOAD", "")
#         secrets_to_load = [s.strip() for s in secrets_to_load_str.split(",") if s.strip()]
#         
#         # Default secrets if not specified
#         if not secrets_to_load:
#             secrets_to_load = [
#                 "dlp-config",      # DLP configuration (all DLP_* env vars)
#                 # Add more secrets as needed:
#                 # "adk-config",    # ADK/agent configuration
#                 # "api-keys",      # API keys
#             ]
#         
#         loaded = load_secrets_at_startup(secret_ids=secrets_to_load)
#         print(f"✓ Loaded {len(loaded)} secrets from Secret Manager: {list(loaded.keys())}")
#         
#     except ImportError:
#         print("⚠ Secret Manager module not available. Using .env values.")
#     except Exception as e:
#         print(f"⚠ Failed to load secrets from Secret Manager: {e}")
#         print("  Falling back to .env values.")

from fastapi import FastAPI
from pydantic import BaseModel

# Import verbose logger
from .logger import get_logger

# Import PII masking plugin
from .pii_masking_plugin import create_pii_masking_plugin
from .dlp_plugin import create_dlp_plugin

# Import the orchestrator and sub agents
from orchestrator.main import OrchestratorAgent
from sub_agent.main import SubAgent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.genai import types

# Create instances of both agents
def init_agents():
    """Initialize all agents."""
    sub_agent = SubAgent()
    orchestrator = OrchestratorAgent(sub_agents=[sub_agent.agent])
    return {
        "orchestrator": orchestrator.agent,
        "sub_agent": sub_agent.agent
    }

# Initialize agents
agents = init_agents()
logger = get_logger()
logger.section("🚀 Orchestrator API Initialization")
logger.success("Agents initialized successfully")
logger.info(f"Available agents: {list(agents.keys())}")

# Create PII masking plugin
logger.step("Creating PII Masking Plugin")
#pii_plugin = create_pii_masking_plugin()
dlp_plugin = create_dlp_plugin(profile="hybrid")
logger.success("PII masking plugin created")

# Create a runner with in-memory services and PII masking plugin
logger.step("Initializing ADK Runner")
logger.debug(f"Root agent: {agents['orchestrator'].name}")
logger.debug(f"Session service: InMemorySessionService")
logger.debug(f"Artifact service: InMemoryArtifactService")
logger.debug(f"Memory service: InMemoryMemoryService")

runner = Runner(
    app_name="OrchestratorAPI",
    agent=agents["orchestrator"],
    session_service=InMemorySessionService(),
    artifact_service=InMemoryArtifactService(),
    memory_service=InMemoryMemoryService(),
    auto_create_session=True,
    #plugins=[pii_plugin, dlp_plugin]
    plugins=[dlp_plugin]  # ADK plugin handles all PII masking automatically
)
logger.success("ADK Runner initialized with PII masking plugin")
logger.debug(f"Plugins: {[plugin.name for plugin in runner.plugin_manager.plugins]}")
logger.info("🏗️  Server ready to accept requests")
logger.section("="*80)

# Create standard FastAPI app
app = FastAPI(title="Orchestrator API")

class ChatRequest(BaseModel):
    message: str

@app.post("/invoke")
async def invoke_agent(request: ChatRequest):
    """Send a prompt to the orchestrator agent."""
    logger.section(f"📨 New Request Received")
    logger.info(f"Request message: {request.message[:200]}{'...' if len(request.message) > 200 else ''}")
    logger.indent()
    
    events = []
    # PII is automatically masked by the plugin at:
    # - User message callback
    # - LLM request callback (covers all context including delegation)
    # - LLM response callback
    
    logger.flow("FastAPI Endpoint", "ADK Runner")
    logger.step("Starting async execution")
    logger.debug(f"User ID: api_user")
    logger.debug(f"Session ID: api_session")
    
    try:
        async for event in runner.run_async(
            user_id="api_user",
            session_id="api_session",
            new_message=types.UserContent(parts=[types.Part(text=request.message)])
        ):
            logger.agent_action(event.author, f"Event received - Final: {event.is_final_response()}")
            logger.debug(f"Event ID: {event.id}")
            
            events.append(event)
            if event.is_final_response():
                response_text = ""
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            response_text += part.text
                
                logger.success("Final response received")
                logger.info(f"Response length: {len(response_text)} characters")
                logger.debug(f"Response preview: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")
                logger.audit("Request Completed", {
                    "user_id": "api_user",
                    "session_id": "api_session",
                    "request_length": len(request.message),
                    "response_length": len(response_text),
                    "events_count": len(events)
                })
                
                logger.dedent()
                logger.section("="*80)
                return {"response": response_text}
        
        logger.warning("No final response received")
        logger.audit("Request Completed - No Final Response", {
            "user_id": "api_user",
            "session_id": "api_session",
            "request_length": len(request.message),
            "events_count": len(events)
        })
        logger.dedent()
        logger.section("="*80)
        return {"response": ""}
    
    except Exception as e:
        logger.error("Error processing request", error=e, details={
            "request_length": len(request.message),
            "events_count": len(events)
        })
        logger.audit("Request Failed", {
            "user_id": "api_user",
            "session_id": "api_session",
            "error_type": type(e).__name__,
            "error_message": str(e)
        })
        logger.dedent()
        logger.section("="*80)
        raise

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.section(f"🌐 Starting FastAPI Server")
    logger.info(f"Host: 0.0.0.0")
    logger.info(f"Port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
