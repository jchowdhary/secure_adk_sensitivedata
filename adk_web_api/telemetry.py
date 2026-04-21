"""OpenTelemetry Configuration and Initialization Module.

This module provides centralized OpenTelemetry setup for:
- Distributed tracing (request flows across agents)
- Metrics collection (latency, throughput, errors)
- Auto-instrumentation for FastAPI, Google GenAI, and async operations
- Log correlation with trace context

Environment Variables:
    OTEL_ENABLED: Enable/disable telemetry (default: "true")
    OTEL_SERVICE_NAME: Service name for traces (default: "adk-agents")
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: "http://localhost:4317")
    OTEL_EXPORTER_OTLP_PROTOCOL: Protocol - "grpc" or "http" (default: "grpc")
    OTEL_EXPORTER_OTLP_HEADERS: Headers for auth (e.g., "api-key=xxx,dd-protocol=otlp")
    OTEL_EXPORTER_TYPE: Exporter type - "otlp", "console", "gcp", or "none" (default: "console")
"""

import os
import logging
import json
import threading
import urllib.request
from typing import Optional, Callable, Dict, Any
from functools import wraps
from datetime import datetime, timedelta

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT

# OTLP Exporters for production use
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    OTLP_AVAILABLE = True
except ImportError:
    OTLP_AVAILABLE = False

# GCP Cloud Trace Exporter
try:
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    GCP_TRACE_AVAILABLE = True
except ImportError:
    GCP_TRACE_AVAILABLE = False

# Instrumentation imports
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FASTAPI_INSTRUMENTOR_AVAILABLE = True
except ImportError:
    FASTAPI_INSTRUMENTOR_AVAILABLE = False

try:
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    LOGGING_INSTRUMENTOR_AVAILABLE = True
except ImportError:
    LOGGING_INSTRUMENTOR_AVAILABLE = False

try:
    from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
    ASYNCIO_INSTRUMENTOR_AVAILABLE = True
except ImportError:
    ASYNCIO_INSTRUMENTOR_AVAILABLE = False

# OpenLLmetry - Google GenAI instrumentation
try:
    from opentelemetry.instrumentation.google_genai import GoogleGenAIInstrumentor
    GENAI_INSTRUMENTOR_AVAILABLE = True
except ImportError:
    GENAI_INSTRUMENTOR_AVAILABLE = False


# Configuration from environment
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() == "true"
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "adk-agents")
OTEL_SERVICE_VERSION = os.getenv("OTEL_SERVICE_VERSION", "1.0.0")
OTEL_DEPLOYMENT_ENV = os.getenv("OTEL_DEPLOYMENT_ENV", os.getenv("ENV", "development"))
OTEL_EXPORTER_TYPE = os.getenv("OTEL_EXPORTER_TYPE", "console")  # "otlp", "console", "gcp", "none"
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
OTEL_EXPORTER_PROTOCOL = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")  # "grpc" or "http"
OTEL_EXPORTER_HEADERS = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")  # comma-separated key=value pairs
OTEL_EXPORTER_TIMEOUT = int(os.getenv("OTEL_EXPORTER_OTLP_TIMEOUT", "10000"))  # milliseconds


def _parse_headers(headers_str: str) -> Dict[str, str]:
    """Parse comma-separated key=value headers string into dict."""
    headers = {}
    if headers_str:
        for pair in headers_str.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                headers[key.strip()] = value.strip()
    return headers

# Global telemetry state
_tracer_provider: Optional[TracerProvider] = None
_meter_provider: Optional[MeterProvider] = None
_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None
_initialized = False


def get_resource() -> Resource:
    """Create OpenTelemetry resource with service metadata."""
    return Resource.create({
        SERVICE_NAME: OTEL_SERVICE_NAME,
        SERVICE_VERSION: OTEL_SERVICE_VERSION,
        DEPLOYMENT_ENVIRONMENT: OTEL_DEPLOYMENT_ENV,
        "service.instance.id": os.getenv("HOSTNAME", "local"),
    })


def get_trace_exporter():
    """Get the appropriate trace exporter based on configuration.
    
    Supported types:
    - 'console': Print traces to stdout (default for development)
    - 'otlp': Send to OTLP collector (supports gRPC and HTTP protocols)
    - 'gcp': Send directly to Google Cloud Trace (requires GCP credentials)
    - 'none': Disable tracing
    
    For OTLP:
    - OTEL_EXPORTER_OTLP_PROTOCOL: "grpc" (default) or "http"
    - OTEL_EXPORTER_OTLP_HEADERS: Authentication headers (e.g., "api-key=xxx")
    - OTEL_EXPORTER_OTLP_TIMEOUT: Timeout in milliseconds
    """
    if OTEL_EXPORTER_TYPE == "none":
        return None
    elif OTEL_EXPORTER_TYPE == "otlp" and OTLP_AVAILABLE:
        headers = _parse_headers(OTEL_EXPORTER_HEADERS)
        
        # Support both gRPC and HTTP protocols
        if OTEL_EXPORTER_PROTOCOL == "http":
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPSpanExporter
                return HTTPSpanExporter(
                    endpoint=OTEL_EXPORTER_ENDPOINT,
                    headers=headers,
                    timeout=OTEL_EXPORTER_TIMEOUT
                )
            except ImportError:
                logging.warning("HTTP OTLP exporter not available, falling back to gRPC")
        
        # Default to gRPC
        return OTLPSpanExporter(
            endpoint=OTEL_EXPORTER_ENDPOINT,
            headers=headers,
            timeout=OTEL_EXPORTER_TIMEOUT
        )
    elif OTEL_EXPORTER_TYPE == "gcp" and GCP_TRACE_AVAILABLE:
        return CloudTraceSpanExporter(project_id=os.getenv("GOOGLE_CLOUD_PROJECT"))
    else:  # console
        return ConsoleSpanExporter()


def get_metric_exporter():
    """Get the appropriate metric exporter based on configuration.
    
    Supports same configuration as trace exporter.
    """
    if OTEL_EXPORTER_TYPE == "none":
        return None
    elif OTEL_EXPORTER_TYPE == "otlp" and OTLP_AVAILABLE:
        headers = _parse_headers(OTEL_EXPORTER_HEADERS)
        
        # Support both gRPC and HTTP protocols
        if OTEL_EXPORTER_PROTOCOL == "http":
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter
                return HTTPMetricExporter(
                    endpoint=OTEL_EXPORTER_ENDPOINT,
                    headers=headers,
                    timeout=OTEL_EXPORTER_TIMEOUT
                )
            except ImportError:
                logging.warning("HTTP OTLP metric exporter not available, falling back to gRPC")
        
        # Default to gRPC
        return OTLPMetricExporter(
            endpoint=OTEL_EXPORTER_ENDPOINT,
            headers=headers,
            timeout=OTEL_EXPORTER_TIMEOUT
        )
    else:  # console
        return ConsoleMetricExporter()


def init_telemetry() -> bool:
    """Initialize OpenTelemetry tracing and metrics.
    
    Returns:
        bool: True if initialization was successful, False otherwise.
    """
    global _tracer_provider, _meter_provider, _tracer, _meter, _initialized
    
    if not OTEL_ENABLED:
        logging.info("OpenTelemetry is disabled via OTEL_ENABLED=false")
        return False
    
    if _initialized:
        return True
    
    try:
        # Create resource
        resource = get_resource()
        
        # Initialize Tracing
        trace_exporter = get_trace_exporter()
        if trace_exporter:
            _tracer_provider = TracerProvider(resource=resource)
            _tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
            trace.set_tracer_provider(_tracer_provider)
            _tracer = trace.get_tracer(OTEL_SERVICE_NAME, OTEL_SERVICE_VERSION)
            logging.info(f"OpenTelemetry tracing initialized (exporter: {OTEL_EXPORTER_TYPE})")
        
        # Initialize Metrics
        metric_exporter = get_metric_exporter()
        if metric_exporter:
            metric_reader = PeriodicExportingMetricReader(
                exporter=metric_exporter,
                export_interval_millis=60000,  # Export every 60 seconds
            )
            _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(_meter_provider)
            _meter = metrics.get_meter(OTEL_SERVICE_NAME, OTEL_SERVICE_VERSION)
            logging.info(f"OpenTelemetry metrics initialized (exporter: {OTEL_EXPORTER_TYPE})")
        
        # Auto-instrument logging (adds trace_id, span_id to log records)
        if LOGGING_INSTRUMENTOR_AVAILABLE:
            LoggingInstrumentor().instrument()
            logging.info("OpenTelemetry logging instrumentation enabled")
        
        # Auto-instrument asyncio
        if ASYNCIO_INSTRUMENTOR_AVAILABLE:
            AsyncioInstrumentor().instrument()
            logging.info("OpenTelemetry asyncio instrumentation enabled")
        
        # Auto-instrument Google GenAI (OpenLLmetry)
        if GENAI_INSTRUMENTOR_AVAILABLE:
            GoogleGenAIInstrumentor().instrument()
            logging.info("OpenLLmetry Google GenAI instrumentation enabled")
        
        # Initialize custom metrics registry for user-defined metrics
        try:
            from .custom_metrics import initialize_custom_metrics
            initialize_custom_metrics(_meter)
            logging.info("Custom metrics registry initialized")
        except ImportError:
            logging.debug("Custom metrics module not available")
        
        _initialized = True
        return True
        
    except Exception as e:
        logging.error(f"Failed to initialize OpenTelemetry: {e}")
        return False


def instrument_fastapi(app):
    """Instrument FastAPI application for automatic request tracing.
    
    Args:
        app: FastAPI application instance
    """
    if not OTEL_ENABLED or not FASTAPI_INSTRUMENTOR_AVAILABLE:
        logging.debug("FastAPI instrumentation skipped (disabled or not available)")
        return
    
    try:
        FastAPIInstrumentor.instrument_app(app)
        logging.info("FastAPI application instrumented for OpenTelemetry")
    except Exception as e:
        logging.error(f"Failed to instrument FastAPI: {e}")


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(OTEL_SERVICE_NAME)
    return _tracer


def get_meter() -> metrics.Meter:
    """Get the global meter instance."""
    global _meter
    if _meter is None:
        _meter = metrics.get_meter(OTEL_SERVICE_NAME)
    return _meter


def get_trace_context() -> dict:
    """Get current trace context for log correlation.
    
    Returns:
        dict: Contains trace_id, span_id, and trace_sampled if in a span context.
    """
    span = trace.get_current_span()
    if span and span.get_span_context():
        ctx = span.get_span_context()
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
            "trace_sampled": ctx.trace_flags.sampled,
        }
    return {"trace_id": None, "span_id": None, "trace_sampled": False}


def traced(name: Optional[str] = None, attributes: Optional[dict] = None):
    """Decorator to automatically trace a function.
    
    Usage:
        @traced("my_operation")
        async def my_function():
            ...
    
    Args:
        name: Span name (defaults to function name)
        attributes: Static attributes to add to the span
    """
    def decorator(func):
        span_name = name or func.__name__
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not OTEL_ENABLED:
                return await func(*args, **kwargs)
            
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                # Add static attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                # Add function metadata
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.module", func.__module__)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("code.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("code.success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not OTEL_ENABLED:
                return func(*args, **kwargs)
            
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.module", func.__module__)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("code.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("code.success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# LLM PRICING - Dynamic fetching from LiteLLM's live pricing data
# =============================================================================

# LiteLLM's live pricing JSON (auto-updated by the community)
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# Cache for pricing data
_pricing_cache: Optional[Dict[str, Any]] = None
_pricing_cache_time: Optional[datetime] = None
_pricing_cache_lock = threading.Lock()
PRICING_CACHE_TTL_HOURS = 24  # Refresh pricing every 24 hours

# Fallback pricing if fetch fails (per 1M tokens in USD)
FALLBACK_PRICING = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}


def _fetch_pricing_from_litellm() -> dict:
    """Fetch live pricing data from LiteLLM's GitHub repository.
    
    Returns:
        dict: Pricing data keyed by model name
    """
    try:
        with urllib.request.urlopen(LITELLM_PRICING_URL, timeout=10) as response:
            data = json.loads(response.read().decode())
            logging.info(f"Fetched live LLM pricing from LiteLLM ({len(data)} models)")
            return data
    except Exception as e:
        logging.warning(f"Failed to fetch LLM pricing from LiteLLM: {e}, using fallback")
        return {}


def _normalize_model_name(model: str) -> str:
    """Normalize model name for pricing lookup.
    
    Handles variations like:
    - gemini-2.5-flash -> gemini-2.5-flash
    - models/gemini-2.5-flash -> gemini-2.5-flash
    - gemini-2.5-flash-001 -> gemini-2.5-flash
    """
    # Remove common prefixes
    model = model.lower()
    for prefix in ["models/", "publishers/google/models/"]:
        if model.startswith(prefix):
            model = model[len(prefix):]
    
    # Remove version suffixes like -001, -002
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        model = parts[0]
    
    return model


def get_model_pricing(model: str) -> dict:
    """Get pricing for a model, checking cache, live data, then fallback.
    
    Args:
        model: Model name (e.g., "gemini-2.5-flash")
    
    Returns:
        dict with 'input' and 'output' prices per 1M tokens in USD
    """
    global _pricing_cache, _pricing_cache_time
    
    # Check environment variable overrides first
    model_lower = model.lower()
    if "flash" in model_lower:
        env_input = os.getenv("LLM_PRICE_FLASH_INPUT")
        env_output = os.getenv("LLM_PRICE_FLASH_OUTPUT")
        if env_input and env_output:
            return {"input": float(env_input), "output": float(env_output)}
    elif "pro" in model_lower:
        env_input = os.getenv("LLM_PRICE_PRO_INPUT")
        env_output = os.getenv("LLM_PRICE_PRO_OUTPUT")
        if env_input and env_output:
            return {"input": float(env_input), "output": float(env_output)}
    
    # Check cache and refresh if needed
    with _pricing_cache_lock:
        now = datetime.utcnow()
        if _pricing_cache is None or (
            _pricing_cache_time and (now - _pricing_cache_time) > timedelta(hours=PRICING_CACHE_TTL_HOURS)
        ):
            _pricing_cache = _fetch_pricing_from_litellm()
            _pricing_cache_time = now
        cache = _pricing_cache
    
    # Normalize model name for lookup
    normalized_model = _normalize_model_name(model)
    
    # Try to find pricing in cached data
    if cache:
        # Try exact match first
        if model in cache:
            entry = cache[model]
            return {"input": entry.get("input_cost_per_token", 0) * 1_000_000,
                    "output": entry.get("output_cost_per_token", 0) * 1_000_000}
        
        # Try normalized match
        if normalized_model in cache:
            entry = cache[normalized_model]
            return {"input": entry.get("input_cost_per_token", 0) * 1_000_000,
                    "output": entry.get("output_cost_per_token", 0) * 1_000_000}
        
        # Try partial match (e.g., "gemini-2.5-flash" in "gemini-2.5-flash-001")
        for model_key, entry in cache.items():
            if normalized_model in model_key.lower() or model_key.lower() in normalized_model:
                return {"input": entry.get("input_cost_per_token", 0) * 1_000_000,
                        "output": entry.get("output_cost_per_token", 0) * 1_000_000}
    
    # Fallback pricing
    for fallback_key, pricing in FALLBACK_PRICING.items():
        if fallback_key in normalized_model or normalized_model in fallback_key:
            return pricing
    
    # Ultimate fallback
    return {"input": 0.10, "output": 0.40}


def estimate_llm_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost of LLM call in USD using live pricing data.
    
    Args:
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
    
    Returns:
        Estimated cost in USD
    """
    pricing = get_model_pricing(model)
    
    # Calculate cost (prices are per 1M tokens)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    
    return input_cost + output_cost


def record_llm_metrics(
    model: str, 
    input_tokens: int, 
    output_tokens: int, 
    latency_ms: float, 
    success: bool = True,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    call_type: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> dict:
    """Record LLM-specific metrics for observability including cost estimation.
    
    This function:
    1. Fetches live pricing from LiteLLM's GitHub (cached for 24h)
    2. Estimates cost based on token usage
    3. Records metrics to OpenTelemetry with correlation/causation tracking
    
    Args:
        model: Model name (e.g., "gemini-2.5-flash")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Request latency in milliseconds
        success: Whether the request succeeded
        correlation_id: Trace-level ID linking all spans in a request chain
        causation_id: Parent span ID for parent-child relationship
        agent_name: Name of the agent making the call
        call_type: Type of call (llm_generation, agent_routing, tool_decision)
        error_code: Error code if the call failed
        error_message: Error message if the call failed
    
    Returns:
        dict with cost estimation and metrics for logging
    """
    # Estimate cost using live pricing
    estimated_cost = estimate_llm_cost(model, input_tokens, output_tokens)
    
    result = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": estimated_cost,
        "success": success,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "agent_name": agent_name,
        "call_type": call_type,
        "error_code": error_code,
        "error_message": error_message,
    }
    
    if not OTEL_ENABLED:
        return result
    
    meter = get_meter()
    
    # Token counters
    input_counter = meter.create_counter(
        "llm.input_tokens",
        unit="tokens",
        description="Number of input tokens sent to LLM"
    )
    output_counter = meter.create_counter(
        "llm.output_tokens",
        unit="tokens",
        description="Number of output tokens received from LLM"
    )
    
    # Latency histogram
    latency_hist = meter.create_histogram(
        "llm.latency",
        unit="ms",
        description="LLM request latency"
    )
    
    # Error counter
    error_counter = meter.create_counter(
        "llm.errors",
        unit="errors",
        description="Number of LLM errors"
    )
    
    # Cost counter (in micros for precision, convert to USD in queries)
    cost_counter = meter.create_counter(
        "llm.cost_usd",
        unit="USD",
        description="Estimated cost of LLM calls in USD"
    )
    
    # Total LLM calls counter
    call_counter = meter.create_counter(
        "llm.calls",
        unit="calls",
        description="Total number of LLM calls"
    )
    
    # Build attributes with correlation/causation IDs
    attrs = {
        "model": model,
        "correlation_id": correlation_id or "",
        "causation_id": causation_id or "",
    }
    if agent_name:
        attrs["agent_name"] = agent_name
    if call_type:
        attrs["call_type"] = call_type
    
    # Record metrics
    input_counter.add(input_tokens, attrs)
    output_counter.add(output_tokens, attrs)
    latency_hist.record(latency_ms, attrs)
    cost_counter.add(estimated_cost, attrs)
    call_counter.add(1, attrs)
    
    if not success:
        error_attrs = {**attrs, "error_code": error_code or ""}
        error_counter.add(1, error_attrs)
    
    # Log cost for visibility
    logging.info(f"LLM Metrics: model={model}, tokens_in={input_tokens}, tokens_out={output_tokens}, "
                 f"latency={latency_ms:.1f}ms, cost=${estimated_cost:.6f}, "
                 f"correlation_id={correlation_id}, success={success}")
    
    return result


def shutdown_telemetry():
    """Shutdown OpenTelemetry providers and flush pending data."""
    global _tracer_provider, _meter_provider
    
    try:
        if _tracer_provider:
            _tracer_provider.shutdown()
            logging.info("OpenTelemetry tracer provider shut down")
        
        if _meter_provider:
            _meter_provider.shutdown()
            logging.info("OpenTelemetry meter provider shut down")
    except Exception as e:
        logging.error(f"Error shutting down OpenTelemetry: {e}")


# Convenience function for getting telemetry status
def get_telemetry_status() -> dict:
    """Get the current telemetry configuration status."""
    return {
        "enabled": OTEL_ENABLED,
        "initialized": _initialized,
        "service_name": OTEL_SERVICE_NAME,
        "environment": OTEL_DEPLOYMENT_ENV,
        "exporter_type": OTEL_EXPORTER_TYPE,
        "exporter_endpoint": OTEL_EXPORTER_ENDPOINT if OTEL_EXPORTER_TYPE in ("otlp", "gcp") else None,
        "exporter_protocol": OTEL_EXPORTER_PROTOCOL if OTEL_EXPORTER_TYPE == "otlp" else None,
        "exporter_headers_configured": bool(OTEL_EXPORTER_HEADERS),
        "exporter_timeout_ms": OTEL_EXPORTER_TIMEOUT,
        "instrumentation": {
            "fastapi": FASTAPI_INSTRUMENTOR_AVAILABLE,
            "logging": LOGGING_INSTRUMENTOR_AVAILABLE,
            "asyncio": ASYNCIO_INSTRUMENTOR_AVAILABLE,
            "google_genai": GENAI_INSTRUMENTOR_AVAILABLE,
        },
        "trace_context": get_trace_context(),
        "pricing_source": "LiteLLM (live)",
        "pricing_cache_age_hours": _get_pricing_cache_age(),
    }


def _get_pricing_cache_age() -> Optional[float]:
    """Get the age of the pricing cache in hours."""
    global _pricing_cache_time
    if _pricing_cache_time:
        age = datetime.utcnow() - _pricing_cache_time
        return age.total_seconds() / 3600
    return None
