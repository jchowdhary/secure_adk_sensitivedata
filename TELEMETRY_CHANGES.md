# OpenTelemetry & OpenLLmetry Implementation Guide

This document describes the telemetry enhancements added to the ADK Agents application, including what was changed, why it matters, and how to use it.

---

## Quick Reference: Switching Exporters

Change where traces are sent by setting environment variables:

| Exporter | Environment Variables | Where Traces Appear |
|----------|----------------------|---------------------|
| **Console** | `OTEL_EXPORTER_TYPE=console` | stdout (terminal) |
| **GCP Cloud Trace** | `OTEL_EXPORTER_TYPE=gcp` + `GOOGLE_CLOUD_PROJECT=your-project` | GCP Console → Trace |
| **Jaeger** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` | http://localhost:16686 |
| **Dynatrace** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_ENDPOINT=https://your-env.live.dynatrace.com/api/v2/otlp` | Dynatrace UI → Distributed traces |
| **Datadog** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_HEADERS=dd-protocol=otlp,dd-api-key=KEY` | Datadog UI → APM |
| **New Relic** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_HEADERS=api-key=LICENSE_KEY` | New Relic UI → Distributed tracing |
| **Honeycomb** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=API_KEY` | Honeycomb UI |
| **Grafana Tempo** | `OTEL_EXPORTER_TYPE=otlp` + `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` | Grafana UI |

### One-Liner Commands

```bash
# Console (development)
OTEL_EXPORTER_TYPE=console uvicorn adk_web_api.main:app

# GCP Cloud Trace (production)
OTEL_EXPORTER_TYPE=gcp GOOGLE_CLOUD_PROJECT=my-project uvicorn adk_web_api.main:app

# Jaeger (local development)
OTEL_EXPORTER_TYPE=otlp OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 uvicorn adk_web_api.main:app

# Dynatrace (production)
OTEL_EXPORTER_TYPE=otlp OTEL_EXPORTER_OTLP_ENDPOINT=https://abc123.live.dynatrace.com/api/v2/otlp OTEL_EXPORTER_OTLP_HEADERS="Authorization=Api-Token dt0c01.abc123..." uvicorn adk_web_api.main:app
```

---

## Summary of Changes

| File | Changes |
|------|---------|
| `requirements.txt` | Added OpenTelemetry and OpenLLmetry packages |
| `adk_web_api/telemetry.py` | **NEW** - Central telemetry configuration module |
| `adk_web_api/logger.py` | Enhanced with structured JSON logging and trace context |
| `adk_web_api/secret_manager.py` | **UPDATED** - Now uses Google Cloud Secret Manager |
| `adk_web_api/main.py` | Added telemetry initialization, FastAPI instrumentation, request tracing |
| `orchestrator/main.py` | Added OpenTelemetry spans to agent invocations |
| `sub_agent/main.py` | Added OpenTelemetry spans to agent invocations |

---

## Why OpenTelemetry?

### Before (Plain Logging)
```
[Log] 10:00:01 - Processing request
[Log] 10:00:02 - Calling orchestrator  
[Log] 10:00:05 - LLM response received
[Log] 10:00:06 - Error: Auth failed
```
**Problems:**
- No correlation between logs from different services
- Cannot trace a request end-to-end
- No performance metrics
- No LLM-specific insights (tokens, costs)

### After (OpenTelemetry)
```
Trace: abc123-xyz789
├─ Span: invoke_agent (duration: 5.2s)
│  ├─ Span: orchestrator.invoke (duration: 0.1s)
│  ├─ Span: sub_agent.invoke (duration: 4.8s)
│  │  └─ Attributes: model=gemini-pro, tokens=1500
│  └─ Span: auth_check (ERROR)
│     └─ Attributes: reason="expired_token"
```
**Benefits:**
- Full request tracing across all components
- Correlated logs with trace IDs
- LLM metrics (tokens, latency, costs)
- Vendor-neutral (works with GCP, AWS, Datadog, etc.)

---

## Key Components

### 1. Telemetry Module (`adk_web_api/telemetry.py`)

Central configuration for OpenTelemetry:

```python
from adk_web_api.telemetry import (
    init_telemetry,           # Initialize at startup
    instrument_fastapi,       # Auto-instrument FastAPI
    get_tracer,               # Get tracer for manual spans
    get_meter,                # Get meter for metrics
    get_trace_context,        # Get current trace IDs
    traced,                   # Decorator for tracing functions
    record_llm_metrics,       # Record LLM-specific metrics
    shutdown_telemetry,       # Cleanup on shutdown
)
```

### 2. Enhanced Logger (`adk_web_api/logger.py`)

The logger now supports:
- **Visual mode** (development): Colored output with emojis
- **Structured mode** (production): JSON logs with trace context

New methods:
- `auth_failure()` - Logs auth failures (category: `auth_failure`)
- `error()` - Logs errors (category: `error`)
- `audit()` - Logs audit events (category: `audit`)
- All logs now include `trace_id` and `span_id` when in a span context

### 3. Auto-Instrumentation

The following are automatically instrumented:
- **FastAPI**: All HTTP requests traced automatically
- **Google GenAI**: LLM calls traced with token usage (OpenLLmetry)
- **Logging**: Log records include trace context
- **Asyncio**: Async operations traced

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENABLED` | `true` | Enable/disable telemetry |
| `OTEL_SERVICE_NAME` | `adk-agents` | Service name in traces |
| `OTEL_SERVICE_VERSION` | `1.0.0` | Service version |
| `OTEL_DEPLOYMENT_ENV` | `development` | Environment (production/staging/development) |
| `OTEL_EXPORTER_TYPE` | `console` | Exporter: `console`, `gcp`, `otlp`, or `none` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP collector endpoint |
| `OTEL_STRUCTURED_LOGS` | `false` | Force structured JSON logs |
| `GOOGLE_CLOUD_PROJECT` | - | GCP project ID (required for `gcp` exporter) |

### LLM Pricing Overrides (Optional)

| Variable | Description |
|----------|-------------|
| `LLM_PRICE_FLASH_INPUT` | Input price for Flash models ($/1M tokens) |
| `LLM_PRICE_FLASH_OUTPUT` | Output price for Flash models ($/1M tokens) |
| `LLM_PRICE_PRO_INPUT` | Input price for Pro models ($/1M tokens) |
| `LLM_PRICE_PRO_OUTPUT` | Output price for Pro models ($/1M tokens) |

---

## Usage Examples

### Local Development (Console Exporter)

```bash
# Default - traces print to console
export OTEL_EXPORTER_TYPE=console
export ENV=development

uvicorn adk_web_api.main:app --reload
```

### Production (OTLP Exporter to GCP)

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
export ENV=production
export OTEL_STRUCTURED_LOGS=true

uvicorn adk_web_api.main:app
```

### Manual Tracing in Code

```python
from adk_web_api.telemetry import get_tracer, traced

# Using decorator
@traced("my_operation", attributes={"custom.attr": "value"})
async def my_function():
    pass

# Manual span
tracer = get_tracer()
with tracer.start_as_current_span("custom_span") as span:
    span.set_attribute("my.key", "my.value")
    # ... do work
```

### Log Categories for Routing

Structured logs include a `log_category` field for filtering:

| Category | Method | Use Case |
|----------|--------|----------|
| `application` | `info()`, `step()`, `success()` | General application logs |
| `auth_failure` | `auth_failure()` | Authentication failures |
| `error` | `error()` | Errors and exceptions |
| `audit` | `audit()` | Audit events |

**Example structured log:**
```json
{
  "timestamp": "2026-04-17T19:00:00.000Z",
  "severity": "ERROR",
  "message": "Authentication failed",
  "logger": "MasterLogger",
  "log_category": "auth_failure",
  "trace_id": "abc123...",
  "span_id": "def456...",
  "details": {"user": "john@example.com"}
}
```

---

## Log Routing with GCP Cloud Logging

To route logs to different Pub/Sub topics based on category:

```bash
# Application logs sink
gcloud logging sinks create app-logs-sink \
  pubsub.googleapis.com/projects/PROJECT/topics/app-logs-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="application"'

# Auth failures sink  
gcloud logging sinks create auth-failures-sink \
  pubsub.googleapis.com/projects/PROJECT/topics/auth-failures-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="auth_failure"'

# Errors sink
gcloud logging sinks create errors-sink \
  pubsub.googleapis.com/projects/PROJECT/topics/errors-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="error"'
```

---

## New API Endpoints

### GET `/telemetry`

Returns current telemetry configuration:

```bash
curl http://localhost:8000/telemetry
```

Response:
```json
{
  "enabled": true,
  "initialized": true,
  "service_name": "adk-agents",
  "environment": "development",
  "exporter_type": "console",
  "instrumentation": {
    "fastapi": true,
    "logging": true,
    "asyncio": true,
    "google_genai": true
  },
  "trace_context": {
    "trace_id": null,
    "span_id": null,
    "trace_sampled": false
  }
}
```

---

## Viewing Traces

### Option 1: Console (Development)

Traces are printed to stdout in JSON format:
```bash
OTEL_EXPORTER_TYPE=console uvicorn adk_web_api.main:app
```

### Option 2: Jaeger (Local)

```bash
# Start Jaeger
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest

# Configure app
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Open Jaeger UI at http://localhost:16686
```

### Option 3: GCP Cloud Trace (Production)

1. Deploy an OpenTelemetry Collector to Cloud Run
2. Configure collector to export to Cloud Trace
3. View traces in GCP Console → Trace

---

## LLM Cost Tracking

### How It Works

LLM costs are calculated dynamically using **LiteLLM's live pricing data**:

1. **Auto-fetches pricing** from [LiteLLM's GitHub](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json)
2. **Caches for 24 hours** - refreshed automatically
3. **Falls back** to defaults if fetch fails
4. **Environment variable overrides** available

### Cost Estimation

```python
from adk_web_api.telemetry import estimate_llm_cost, record_llm_metrics

# Estimate cost for a call
cost = estimate_llm_cost("gemini-2.5-flash", input_tokens=1000, output_tokens=500)
print(f"Cost: ${cost:.6f}")  # e.g., Cost: $0.000157

# Record metrics with cost
result = record_llm_metrics(
    model="gemini-2.5-flash",
    input_tokens=1000,
    output_tokens=500,
    latency_ms=1500,
    success=True
)
# Returns: {"model": ..., "cost_usd": 0.000157, ...}
```

### Environment Variable Overrides (Optional)

If you want to override live pricing:

```bash
export LLM_PRICE_FLASH_INPUT=0.075   # $/1M tokens
export LLM_PRICE_FLASH_OUTPUT=0.30
export LLM_PRICE_PRO_INPUT=1.25
export LLM_PRICE_PRO_OUTPUT=5.00
```

---

## Where to View Traces

### Option 1: Console (Development)

Default - traces print to stdout:
```bash
OTEL_EXPORTER_TYPE=console uvicorn adk_web_api.main:app
```

### Option 2: GCP Cloud Trace (Production - Recommended)

**Direct export to GCP Cloud Trace** (no collector needed):

```bash
# Set environment variables
export OTEL_EXPORTER_TYPE=gcp
export GOOGLE_CLOUD_PROJECT=your-project-id

# Run the app - traces go directly to Cloud Trace
uvicorn adk_web_api.main:app
```

View traces: **GCP Console → Trace → Trace List**

### Option 3: OTLP Collector (Jaeger, Datadog, Grafana Tempo, etc.)

Send traces to any OTLP-compatible backend:

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

See the **Exporting to External Backends** section below for detailed configuration.

---

## Exporting to External Backends

### Overview

OpenTelemetry supports multiple exporters through the OTLP protocol. You can send telemetry to:

| Backend | Protocol | Endpoint |
|---------|----------|----------|
| Jaeger | OTLP gRPC | `jaeger:4317` |
| Datadog | OTLP gRPC | `datadog-agent:4317` |
| Grafana Tempo | OTLP gRPC | `tempo:4317` |
| New Relic | OTLP HTTP | `https://otlp.nr-data.net:4318` |
| Elastic APM | OTLP gRPC | `apm-server:8200` |
| Azure Monitor | OTLP HTTP | `https://dc.services.visualstudio.com` |

### Configuration Parameters

#### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_EXPORTER_TYPE` | `console` | `gcp`, `otlp`, `console`, or `none` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP collector endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http` |
| `OTEL_EXPORTER_OTLP_HEADERS` | - | Headers for authentication (e.g., API keys) |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | `10000` | Timeout in milliseconds |

### Jaeger Setup

#### Local Development (Docker)

```yaml
# docker-compose.jaeger.yaml
version: '3.8'
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
    environment:
      - COLLECTOR_OTLP_ENABLED=true

  adk-agents:
    build: .
    ports:
      - "8000:8080"
    environment:
      - OTEL_EXPORTER_TYPE=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
      - GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
```

```bash
# Start Jaeger + App
docker-compose -f docker-compose.jaeger.yaml up

# Open Jaeger UI
open http://localhost:16686
```

#### Environment Variables for Jaeger

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
```

### Dynatrace Setup

Dynatrace supports OpenTelemetry via OTLP protocol. You can send traces directly to Dynatrace SaaS or through a Dynatrace OneAgent.

#### Environment Variables for Dynatrace

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_ENVIRONMENT_ID.live.dynatrace.com/api/v2/otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Api-Token YOUR_API_TOKEN"
```

#### Getting Dynatrace Credentials

1. **Environment ID**: Found in Dynatrace UI → Settings → Deployment → OneAgent
2. **API Token**: Create in Dynatrace UI → Settings → Integration → Dynatrace API → Tokens
   - Required permission: `DataExport` (for sending telemetry)

#### Direct OTLP to Dynatrace SaaS

```bash
# Replace YOUR_ENV_ID and YOUR_API_TOKEN
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_ENV_ID.live.dynatrace.com/api/v2/otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Api-Token dt0c01.YOUR_TOKEN"

uvicorn adk_web_api.main:app
```

#### Using Dynatrace OneAgent (Kubernetes/Cloud Run)

If OneAgent is installed on your infrastructure, you can use the local endpoint:

```bash
# OneAgent provides a local OTLP endpoint
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# No API token needed - OneAgent handles authentication
```

#### Docker Compose with Dynatrace

```yaml
# docker-compose.dynatrace.yaml
version: '3.8'
services:
  adk-agents:
    build: .
    ports:
      - "8000:8080"
    environment:
      - OTEL_EXPORTER_TYPE=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=https://${DYNATRACE_ENV_ID}.live.dynatrace.com/api/v2/otlp
      - OTEL_EXPORTER_OTLP_PROTOCOL=http
      - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Api-Token ${DYNATRACE_API_TOKEN}
      - GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
```

```bash
# Start with Dynatrace
export DYNATRACE_ENV_ID=abc12345
export DYNATRACE_API_TOKEN=dt0c01.abc123...
docker-compose -f docker-compose.dynatrace.yaml up
```

#### View Traces in Dynatrace

1. Open Dynatrace UI
2. Navigate to **Distributed traces** in the left menu
3. Filter by service name `adk-agents`
4. Click on a trace to see the full request flow

### Datadog Setup

#### Using Datadog Agent

```yaml
# docker-compose.datadog.yaml
version: '3.8'
services:
  datadog-agent:
    image: gcr.io/datadoghq/agent:latest
    environment:
      - DD_API_KEY=${DD_API_KEY}
      - DD_SITE=datadoghq.com
    ports:
      - "4317:4317"  # OTLP gRPC
      - "4318:4318"  # OTLP HTTP

  adk-agents:
    build: .
    ports:
      - "8000:8080"
    environment:
      - OTEL_EXPORTER_TYPE=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://datadog-agent:4317
      - GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
```

#### Environment Variables for Datadog

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Datadog-specific headers
export OTEL_EXPORTER_OTLP_HEADERS="dd-protocol=otlp"
```

#### Datadog SaaS (No Agent)

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://trace.agent.datadoghq.com
export OTEL_EXPORTER_OTLP_HEADERS="dd-protocol=otlp,dd-api-key=${DD_API_KEY}"
# Note: Headers must be quoted and comma-separated without spaces
```

### Grafana Tempo Setup

```yaml
# docker-compose.tempo.yaml
version: '3.8'
services:
  tempo:
    image: grafana/tempo:latest
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml
    command: -config.file=/etc/tempo.yaml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true

  adk-agents:
    build: .
    ports:
      - "8000:8080"
    environment:
      - OTEL_EXPORTER_TYPE=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
```

```bash
# tempo.yaml
server:
  http_listen_port: 4318

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo
```

```bash
# Start Tempo + Grafana + App
docker-compose -f docker-compose.tempo.yaml up

# Open Grafana UI
open http://localhost:3000
```

### New Relic Setup

```bash
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp.nr-data.net:4317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_HEADERS="api-key=${NEW_RELIC_LICENSE_KEY}"
# Note: Headers must be quoted and comma-separated without spaces
```

### API Keys by Backend

Different observability backends use different header names and require different types of API keys. Here's a quick reference:

**Datadog**
- Header: `dd-api-key`
- Key Type: API Key
- Where to get: [Datadog UI → Organization Settings → API Keys](https://app.datadoghq.com/organization-settings/api-keys)

**New Relic**
- Header: `api-key`
- Key Type: License Key
- Where to get: [New Relic UI → API Keys](https://one.newrelic.com/launcher/api-keys-ui/api-keys)

**Grafana Cloud**
- Header: `Authorization: Bearer`
- Key Type: API Token
- Where to get: Grafana Cloud Portal → Settings → API Tokens

**Honeycomb**
- Header: `x-honeycomb-team`
- Key Type: API Key
- Where to get: Honeycomb UI → Team Settings → API Keys

**Jaeger**
- Header: *(none)*
- Key Type: No key required
- Usage: Local development only

#### Header Examples by Backend

```bash
# Datadog SaaS (direct to Datadog)
OTEL_EXPORTER_OTLP_HEADERS="dd-protocol=otlp,dd-api-key=${DD_API_KEY}"

# New Relic
OTEL_EXPORTER_OTLP_HEADERS="api-key=${NEW_RELIC_LICENSE_KEY}"

# Grafana Cloud Tempo
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${GRAFANA_TOKEN}"

# Honeycomb
OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=${HONEYCOMB_API_KEY}"

# Jaeger (local - no authentication needed)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# No OTEL_EXPORTER_OTLP_HEADERS required
```

#### Getting Started Locally (No API Key Required)

For local development, use Jaeger - no API key or account needed:

```bash
# Start Jaeger in Docker
docker run -d --name jaeger \
  -p 16686:16686 \   # UI
  -p 4317:4317 \    # OTLP gRPC
  -p 4318:4318 \    # OTLP HTTP
  jaegertracing/all-in-one:latest

# Configure your app
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Open Jaeger UI to view traces
open http://localhost:16686
```

### Multiple Exporters (Advanced)

To send telemetry to multiple backends simultaneously, you need to configure an **OpenTelemetry Collector** that fans out to multiple destinations.

#### Collector Configuration

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 1s
    send_batch_size: 1024

exporters:
  # Export to Jaeger
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

  # Export to Datadog
  otlp/datadog:
    endpoint: datadog-agent:4317
    tls:
      insecure: true

  # Export to GCP Cloud Trace
  googlecloud:
    project: your-project-id

  # Export to console (debugging)
  logging:
    loglevel: debug

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger, otlp/datadog, googlecloud]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [googlecloud, logging]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [googlecloud, logging]
```

#### Docker Compose with Collector

```yaml
# docker-compose.multi-backend.yaml
version: '3.8'
services:
  # OpenTelemetry Collector
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    volumes:
      - ./otel-collector-config.yaml:/etc/otelcol/config.yaml
    ports:
      - "4317:4317"   # OTLP gRPC receiver
      - "4318:4318"   # OTLP HTTP receiver
    command: --config=/etc/otelcol/config.yaml

  # Jaeger for local visualization
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"

  # Datadog Agent
  datadog-agent:
    image: gcr.io/datadoghq/agent:latest
    environment:
      - DD_API_KEY=${DD_API_KEY}

  # Your App
  adk-agents:
    build: .
    ports:
      - "8000:8080"
    environment:
      - OTEL_EXPORTER_TYPE=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
      - GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
      - LOAD_FROM_SECRET_MANAGER=false
```

```bash
# Start all services
docker-compose -f docker-compose.multi-backend.yaml up

# View traces in:
# - Jaeger: http://localhost:16686
# - Datadog: https://app.datadoghq.com
# - GCP Cloud Trace: https://console.cloud.google.com/traces
```

### Environment Variables Summary by Backend

#### For .env or Cloud Run

```bash
# === Jaeger ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# === Datadog (with agent) ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://datadog-agent:4317

# === Datadog (SaaS) ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://trace.agent.datadoghq.com
OTEL_EXPORTER_OTLP_HEADERS=dd-protocol=otlp,dd-api-key=${DD_API_KEY}

# === Dynatrace ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://${DYNATRACE_ENV_ID}.live.dynatrace.com/api/v2/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Api-Token ${DYNATRACE_API_TOKEN}

# === Grafana Tempo ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317

# === New Relic ===
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp.nr-data.net:4317
OTEL_EXPORTER_OTLP_HEADERS=api-key=${NEW_RELIC_LICENSE_KEY}

# === GCP Cloud Trace (no collector needed) ===
OTEL_EXPORTER_TYPE=gcp
GOOGLE_CLOUD_PROJECT=your-project-id

# === Console (debugging) ===
OTEL_EXPORTER_TYPE=console
```

### Production Architecture with Collector

```
┌─────────────┐      ┌────────────────────┐      ┌─────────────────┐
│ Cloud Run   │      │  OTel Collector    │      │    Backends     │
│ (App)       │─────▶│  (K8s/Cloud Run)   │─────▶│                 │
└─────────────┘      └────────────────────┘      │  ┌───────────┐  │
                             │                   │  │ Jaeger    │  │
                             │                   │  ├───────────┤  │
                             │                   │  │ Datadog   │  │
                             │                   │  ├───────────┤  │
                             │                   │  │ Tempo     │  │
                             │                   │  ├───────────┤  │
                             │                   │  │ GCP Trace │  │
                             │                   │  └───────────┘  │
                             │                   └─────────────────┘
                             │
                             └────────────────────────────────────────▶
                                   (fan-out to multiple backends)
```

### Deploying Collector to Cloud Run

```bash
# Deploy OTel Collector to Cloud Run
gcloud run deploy otel-collector \
  --image=otel/opentelemetry-collector-contrib:latest \
  --region=$REGION \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --command="/otelcol-contrib" \
  --args="--config=/etc/otelcol/config.yaml"

# Update app to use collector
export OTEL_EXPORTER_TYPE=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector-XXXX.run.app
```

---

## Telemetry Plugin for Comprehensive LLM Observability

The `TelemetryPlugin` captures all LLM-related events through ADK's callback system, providing comprehensive observability for your agent application.

### What the Plugin Captures

#### LLM Call Events
All LLM API calls are captured with:

- `llm.calls` (Counter) - Total LLM calls made
- `llm.input_tokens` (Counter) - Input tokens consumed
- `llm.output_tokens` (Counter) - Output tokens generated
- `llm.latency` (Histogram) - LLM call latency
- `llm.cost_usd` (Counter) - Estimated cost in USD
- `llm.errors` (Counter) - LLM call failures
- `llm.routing_decisions` (Counter) - Agent/workflow routing decisions

#### Tool/MCP Call Events
All tool and MCP calls are captured with:

- `tool.calls` (Counter) - Total tool calls made
- `tool.latency` (Histogram) - Tool call latency
- `tool.errors` (Counter) - Tool call failures

### Correlation and Causation IDs

Every span includes correlation and causation IDs for distributed tracing:

**Correlation ID** (`correlation_id`)
- Trace-level ID that remains constant throughout the entire request lifecycle
- Links all spans together across agents, LLM calls, and tool calls
- Format: `corr-{invocation_id}` or UUID

**Causation ID** (`causation_id`)
- Parent span ID for the current operation
- Tracks parent-child relationships between spans
- Enables visualization of call hierarchies

### Call Types Captured

The plugin categorizes LLM calls by type:

- `llm_generation` - Standard content generation
- `agent_routing` - Orchestrator deciding which subagent to call
- `tool_decision` - Agent deciding which tool to use
- `workflow_routing` - Agent deciding which workflow to trigger

### Tool Types Captured

Tools are categorized by type:

- `mcp` - Model Context Protocol tool
- `function` - Python function tool
- `api` - External API call tool

### Span Attributes

Every span includes these attributes:

```python
{
    # Identifiers
    "call_id": "unique_span_id",
    "correlation_id": "corr-invocation-123",
    "causation_id": "parent_span_id",
    "invocation_id": "invocation-123",
    
    # LLM details
    "model": "gemini-2.5-flash",
    "agent_name": "orchestrator",
    "call_type": "agent_routing",
    
    # Metrics
    "input_tokens": 150,
    "output_tokens": 80,
    "latency_ms": 1234.56,
    "cost_usd": 0.000123,
    "success": true,
    
    # Error info (if failed)
    "error_code": "RESOURCE_EXHAUSTED",
    "error_message": "Rate limit exceeded"
}
```

### Querying Metrics

#### Query by Correlation ID (full request chain)
```sql
-- All events in a single request
SELECT * FROM spans 
WHERE attributes['correlation_id'] = 'corr-abc123'
ORDER by timestamp;
```

#### Query by Call Type
```sql
-- All agent routing decisions
SELECT * FROM spans 
WHERE attributes['call_type'] = 'agent_routing';
```

#### Query for Errors
```sql
-- All failed LLM calls
SELECT * FROM spans 
WHERE attributes['success'] = false
AND span_name LIKE 'llm_call%';
```

#### Aggregated Metrics (PromQL)
```promql
# Total LLM calls by model
sum by (model) (llm_calls_total)

# Token usage rate
rate(llm_input_tokens_total[5m])

# Error rate
sum by (model) (rate(llm_errors_total[5m]))

# Cost per model
sum by (model) (llm_cost_usd_total)

# Tool call latency P99
histogram_quantile(0.99, tool_latency_bucket)
```

### Integration with DLP Plugin

The TelemetryPlugin works alongside the DLP plugin:

```python
# Both plugins are automatically registered
plugins=[telemetry_plugin, dlp_plugin]
```

- **TelemetryPlugin**: Captures metrics and traces
- **DLPPlugin**: Handles PII masking

Both plugins observe the same callbacks but perform different functions.

---

## Custom Metrics and Error Tracking

The telemetry system now includes comprehensive error categorization and support for user-defined custom metrics.

### Error Categories Tracked

Errors are automatically categorized for better monitoring:

- `rate_limit` - API rate limits (429, RESOURCE_EXHAUSTED, quota exceeded)
- `timeout` - Request timeouts (TIMEOUT, DEADLINE_EXCEEDED)
- `authentication` - Auth failures (401, UNAUTHENTICATED, Invalid API key)
- `authorization` - Permission errors (403, PERMISSION_DENIED)
- `resource_exhausted` - Resource limits (OUT_OF_MEMORY)
- `invalid_request` - Bad requests (400, INVALID_ARGUMENT)
- `model_not_found` - Model not available (404, NOT_FOUND)
- `content_filtered` - Safety blocks (SAFETY, blocked, prohibited)
- `network_error` - Connection issues (503, UNAVAILABLE, connection refused)
- `internal_error` - Server errors (500, INTERNAL)

### Built-in Error Metrics

These metrics are automatically recorded:

- `errors.by_category` - Errors categorized by type
- `retries.total` - Total retry attempts
- `fallbacks.total` - Fallback events (model switching)
- `secret_manager.loads` - Secret Manager operations
- `secret_manager.latency` - Secret Manager latency
- `secret_manager.errors` - Secret Manager errors

### Human-in-the-Loop (HITL) Metrics

For workflows where agents escalate decisions or tasks to human reviewers, use the built-in `HITLMetrics` class:

```python
from adk_web_api.custom_metrics import HITLMetrics

# Record when an AI escalates a task to a human queue
HITLMetrics.record_escalation(
    escalation_type="low_confidence",
    reason="Confidence score below 0.6",
    agent_id="orchestrator",
    attributes={"user_tier": "premium"}
)

# Record the completion of a human review
HITLMetrics.record_review_completed(
    reviewer_id="agent_smith",
    duration_ms=45000,     # Time taken by human to review
    queue_time_ms=120000,  # Time spent waiting in the queue
    decision="override"
)
```

### Adding Custom Business Metrics

You can easily add custom business metrics (like checkout attempts, user signups, or specific feature usage) to track your application's business performance alongside LLM metrics.

#### Step 1: Get the Registry and Register Your Metric
First, retrieve the `CustomMetricsRegistry` singleton and register your metric (Counter or Histogram) before you use it. This is typically done at startup or in your specific service module.

```python
from adk_web_api.custom_metrics import CustomMetricsRegistry

# Get the singleton registry
registry = CustomMetricsRegistry.get_instance()

# Register a counter for business events
registry.register_counter(
    name="business.checkouts",
    description="Number of checkout attempts",
    unit="count"
)

# Register a histogram for processing time
registry.register_histogram(
    name="business.validation_time",
    description="Time to validate user input",
    unit="ms"
)

# Emit metrics
registry.emit_counter("business.checkouts", value=1, attributes={
    "user_tier": "premium",
    "payment_method": "credit_card"
})

registry.emit_histogram("business.validation_time", value=45.2, attributes={
    "validation_type": "address"
})
```

### Using Event Hooks

Register callbacks to react to telemetry events:

```python
from adk_web_api.custom_metrics import MetricsHooks

# Callback for LLM events
def on_llm_complete(event_type, data):
    if not data.get("success"):
        # Log to external system on failure
        send_alert(
            f"LLM failed: {data['error_code']} - {data['error_message']}"
        )
    
    # Update business metrics
    if data.get("call_type") == "agent_routing":
        track_routing_decision(data["model"], data["latency_ms"])

# Register the callback
MetricsHooks.on_llm_call_end(on_llm_complete)

# Available hooks:
MetricsHooks.on_llm_call_start(callback)    # Before LLM call
MetricsHooks.on_llm_call_end(callback)      # After LLM call
MetricsHooks.on_tool_call_start(callback)   # Before tool call
MetricsHooks.on_tool_call_end(callback)     # After tool call
MetricsHooks.on_error(callback)             # On any error
MetricsHooks.on_retry(callback)             # On retry attempt
MetricsHooks.on_fallback(callback)          # On model/config fallback
```

### Manual Error Recording

```python
from adk_web_api.custom_metrics import record_error_with_category

try:
    result = llm_client.generate(prompt)
except Exception as e:
    # Categorize and record the error
    categorized = record_error_with_category(
        error=e,
        error_code="RESOURCE_EXHAUSTED",
        error_message="Rate limit exceeded",
        correlation_id="corr-abc123"
    )
    
    # Check if retryable
    if categorized.is_retryable:
        backoff = categorized.suggested_backoff_ms
        time.sleep(backoff / 1000)
        retry()
```

---

## Dependencies Added

```txt
# OpenTelemetry Core
opentelemetry-distro>=0.48b0
opentelemetry-api>=1.27.0
opentelemetry-sdk>=1.27.0

# OpenTelemetry Exporters
opentelemetry-exporter-otlp>=1.27.0
opentelemetry-exporter-otlp-proto-grpc>=1.27.0
opentelemetry-exporter-otlp-proto-http>=1.27.0
opentelemetry-exporter-google-cloud-trace>=0.17b0
opentelemetry-exporter-google-cloud-monitoring>=0.17b0

# OpenTelemetry Instrumentation
opentelemetry-instrumentation-fastapi>=0.48b0
opentelemetry-instrumentation-requests>=0.48b0
opentelemetry-instrumentation-asyncio>=0.48b0
opentelemetry-instrumentation-logging>=0.48b0
opentelemetry-instrumentation-system-metrics>=0.48b0

# OpenLLmetry - LLM Observability
opentelemetry-instrumentation-google-genai>=0.1.0
```

---

## Migration Checklist

- [ ] Install new dependencies: `pip install -r requirements.txt`
- [ ] Set environment variables for your environment
- [ ] Test locally with console exporter
- [ ] Configure OTLP collector for production
- [ ] Set up Cloud Logging sinks for log routing
- [ ] Monitor traces in your observability platform

---

## Troubleshooting

### Traces not appearing
1. Check `OTEL_ENABLED=true`
2. Verify exporter type and endpoint
3. Check `/telemetry` endpoint for initialization status

### Missing LLM metrics
1. Ensure `opentelemetry-instrumentation-google-genai` is installed
2. Check that `GoogleGenAIInstrumentor` is enabled in telemetry status
3. Verify TelemetryPlugin is loaded: check logs for "Telemetry Plugin Initialized"

### Missing token counts or cost data
1. TelemetryPlugin extracts tokens from `llm_response.usage_metadata`
2. Some models may not return usage metadata
3. Check logs for "LLM call completed" entries

### Correlation ID not appearing
1. Correlation ID is set at user message callback
2. Ensure TelemetryPlugin is registered in Runner plugins list
3. Check that the request reaches the agent system

### Tool call metrics missing
1. TelemetryPlugin hooks into `before_tool_callback` and `after_tool_callback`
2. Only applies if tools are actually called during the request
3. Check logs for "Tool call started/completed" entries

### Logs missing trace context
1. Ensure OpenTelemetry is initialized before logging
2. Check that `opentelemetry-instrumentation-logging` is installed
3. Verify structured logging is enabled in production

---

## References

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Complete Cloud Run deployment guide
- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/languages/python/)
- [OpenLLmetry GitHub](https://github.com/traceloop/openllmetry)
- [GCP Cloud Trace](https://cloud.google.com/trace)
- [Google Cloud Secret Manager](https://cloud.google.com/secret-manager/docs)
