"""FastAPI entry point for ADK agents with OpenTelemetry instrumentation."""

import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# OPENTELEMETRY INITIALIZATION (MUST BE BEFORE OTHER IMPORTS)
# ============================================================================
from .telemetry import (
    init_telemetry,
    instrument_fastapi,
    get_tracer,
    get_trace_context,
    get_telemetry_status,
    shutdown_telemetry,
)

# Initialize telemetry before any other imports that might use it
telemetry_initialized = init_telemetry()

# ============================================================================
# SECRET MANAGER STARTUP LOADING
# ============================================================================
# Load DLP configuration from Google Cloud Secret Manager
#
# Environment variables:
# - LOAD_FROM_SECRET_MANAGER=true  (required)
# - SECRETS_TO_LOAD=dlp-config     (comma-separated list)
#
# The secret should contain JSON with DLP_* keys that will be loaded into
# environment variables before the DLP plugin is initialized.
# ============================================================================

secret_manager_status = {
    "enabled": False,
    "success": False,
    "requested_secrets": [],
    "loaded_secrets": [],
    "loaded_env_keys": [],
    "error": None,
}

load_from_secret_manager = os.getenv("LOAD_FROM_SECRET_MANAGER", "false").lower() == "true"
secret_manager_status["enabled"] = load_from_secret_manager

if load_from_secret_manager:
    try:
        from .secret_manager import load_secrets_at_startup

        secrets_to_load_str = os.getenv("SECRETS_TO_LOAD", "dlp-config")
        secrets_to_load = [
            s.strip() for s in secrets_to_load_str.split(",") if s.strip()
        ]

        if not secrets_to_load:
            secrets_to_load = ["dlp-config"]

        secret_manager_status["requested_secrets"] = secrets_to_load
        loaded = load_secrets_at_startup(secret_ids=secrets_to_load)
        secret_manager_status["success"] = True
        secret_manager_status["loaded_secrets"] = list(loaded.keys())
        secret_manager_status["loaded_env_keys"] = sorted(
            key for env_vars in loaded.values() for key in env_vars.keys()
        )

        os.environ["SECRET_MANAGER_LOAD_STATUS"] = "success"
        os.environ["SECRET_MANAGER_LOADED_SECRETS"] = ",".join(
            secret_manager_status["loaded_secrets"]
        )
        os.environ["SECRET_MANAGER_LOADED_KEYS"] = ",".join(
            secret_manager_status["loaded_env_keys"]
        )

        print(f"Loaded {len(loaded)} secrets from Secret Manager: {list(loaded.keys())}")
        print(
            "Secret Manager loaded env keys: "
            f"{secret_manager_status['loaded_env_keys']}"
        )

    except ImportError:
        secret_manager_status["error"] = "Secret Manager module not available"
        os.environ["SECRET_MANAGER_LOAD_STATUS"] = "import_error"
        print("Secret Manager module not available. Install: pip install google-cloud-secret-manager")
    except Exception as e:
        secret_manager_status["error"] = str(e)
        os.environ["SECRET_MANAGER_LOAD_STATUS"] = "error"
        print(f"Failed to load secrets from Secret Manager: {e}")
        print("Falling back to .env values.")
else:
    os.environ["SECRET_MANAGER_LOAD_STATUS"] = "disabled"

from fastapi import FastAPI
from pydantic import BaseModel

# Import verbose logger
from .logger import get_logger

# Import PII masking plugin
from .pii_masking_plugin import create_pii_masking_plugin
from .dlp_plugin import create_dlp_plugin

# Import Telemetry Plugin for LLM observability
from .telemetry_plugin import create_telemetry_plugin
from .telemetry_plugin import (
    total_request_cost,
    total_input_tokens,
    total_output_tokens
)

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
logger.subsection("Secret Manager Verification")
logger.info(f"Enabled: {secret_manager_status['enabled']}")
logger.info(f"Load status: {os.getenv('SECRET_MANAGER_LOAD_STATUS', 'unknown')}")
logger.info(f"Requested secrets: {secret_manager_status['requested_secrets']}")
logger.info(f"Loaded secrets: {secret_manager_status['loaded_secrets']}")
logger.info(f"Loaded env keys: {secret_manager_status['loaded_env_keys']}")
logger.info(f"DLP_PROVIDER after startup: {os.getenv('DLP_PROVIDER', '<not set>')}")
logger.info(f"DLP_ACTION after startup: {os.getenv('DLP_ACTION', '<not set>')}")
if secret_manager_status["error"]:
    logger.warning(
        "Secret Manager load reported an error",
        details={"error": secret_manager_status["error"]},
    )

# Create PII masking plugin
logger.step("Creating PII Masking Plugin")
#pii_plugin = create_pii_masking_plugin()
dlp_plugin = create_dlp_plugin(profile="hybrid")
telemetry_plugin = create_telemetry_plugin()
logger.success("PII masking plugin created")
logger.success("Telemetry plugin created")

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
    plugins=[telemetry_plugin, dlp_plugin]  # Telemetry for LLM metrics, DLP for PII masking
)
logger.success("ADK Runner initialized with telemetry and PII masking plugins")
logger.debug(f"Plugins: {[plugin.name for plugin in runner.plugin_manager.plugins]}")
logger.info("🏗️  Server ready to accept requests")
logger.section("="*80)

# Create standard FastAPI app
app = FastAPI(title="Orchestrator API")

# Instrument FastAPI for OpenTelemetry automatic request tracing
instrument_fastapi(app)

# Log telemetry status
logger.subsection("OpenTelemetry Status")
telemetry_status = get_telemetry_status()
logger.info(f"Telemetry enabled: {telemetry_status['enabled']}")
logger.info(f"Telemetry initialized: {telemetry_status['initialized']}")
logger.info(f"Service name: {telemetry_status['service_name']}")
logger.info(f"Environment: {telemetry_status['environment']}")
logger.info(f"Exporter type: {telemetry_status['exporter_type']}")
logger.info(f"Instrumentation: {telemetry_status['instrumentation']}")


class ChatRequest(BaseModel):
    message: str

@app.post("/invoke")
async def invoke_agent(request: ChatRequest):
    """Send a prompt to the orchestrator agent with OpenTelemetry tracing."""
    tracer = get_tracer()
    start_time = time.time()
    
    # Reset context vars to aggregate total metrics for this specific trace
    total_request_cost.set(0.0)
    total_input_tokens.set(0)
    total_output_tokens.set(0)
    
    # Create a span for the entire request
    with tracer.start_as_current_span("invoke_agent") as span:
        # Add request metadata to span
        span.set_attribute("request.message_length", len(request.message))
        span.set_attribute("request.user_id", "api_user")
        span.set_attribute("request.session_id", "api_session")
        
        logger.section(f"📨 New Request Received")
        logger.info(f"Request message: {request.message[:200]}{'...' if len(request.message) > 200 else ''}")
        
        # Log trace context for correlation
        trace_ctx = get_trace_context()
        if trace_ctx.get("trace_id"):
            logger.info(f"Trace ID: {trace_ctx['trace_id']}")
            span.set_attribute("trace.id", trace_ctx['trace_id'])
        
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
                    
                    # Calculate latency
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Capture aggregated cost and tokens
                    agg_cost = total_request_cost.get()
                    agg_in = total_input_tokens.get()
                    agg_out = total_output_tokens.get()
                    
                    # Add response metadata to span
                    span.set_attribute("response.length", len(response_text))
                    span.set_attribute("response.events_count", len(events))
                    span.set_attribute("response.latency_ms", latency_ms)
                    span.set_attribute("request.total_cost_usd", agg_cost)
                    span.set_attribute("request.total_input_tokens", agg_in)
                    span.set_attribute("request.total_output_tokens", agg_out)
                    span.set_attribute("success", True)
                    
                    logger.success("Final response received")
                    logger.info(f"Response length: {len(response_text)} characters")
                    logger.info(f"Latency: {latency_ms:.2f}ms")
                    logger.info(f"Total Request Execution: Cost=${agg_cost:.6f} | Tokens: {agg_in} In / {agg_out} Out")
                    logger.debug(f"Response preview: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")
                    logger.audit("Request Completed", {
                        "user_id": "api_user",
                        "session_id": "api_session",
                        "request_length": len(request.message),
                        "response_length": len(response_text),
                        "events_count": len(events),
                        "latency_ms": latency_ms,
                        "total_cost_usd": agg_cost,
                        "total_tokens": agg_in + agg_out
                    })
                    
                    logger.dedent()
                    logger.section("="*80)
                    return {"response": response_text}
            
            # No final response
            span.set_attribute("success", False)
            span.set_attribute("error.type", "no_final_response")
            
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
            # Record error in span
            span.set_attribute("success", False)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            span.record_exception(e)
            
            # Add categorized error trace to metrics
            try:
                from .custom_metrics import SystemAndRuntimeMetrics
                categorized = SystemAndRuntimeMetrics.record_and_categorize(
                    error=e,
                    correlation_id=trace_ctx.get("trace_id", "unknown")
                )
                span.set_attribute("error.category", categorized.category.value)
            except ImportError:
                pass
            
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

@app.get("/telemetry")
async def get_telemetry_info():
    """Get current OpenTelemetry configuration and trace context."""
    return get_telemetry_status()


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown - flush telemetry data."""
    logger.info("Shutting down...")
    shutdown_telemetry()
    logger.success("Telemetry shutdown complete")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.section(f"🌐 Starting FastAPI Server")
    logger.info(f"Host: 0.0.0.0")
    logger.info(f"Port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
