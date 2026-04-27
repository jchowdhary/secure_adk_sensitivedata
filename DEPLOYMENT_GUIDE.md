# ADK Agents Deployment Guide

Complete guide for deploying ADK Agents to Google Cloud Run with DLP, Secret Manager, and OpenTelemetry observability.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Run Service                            │
│                      (adk-agents)                                │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐        │
│  │  FastAPI    │───▶│ Orchestrator │───▶│  Sub Agent   │        │
│  │  /invoke    │    │    Agent     │    │              │        │
│  └─────────────┘    └──────────────┘    └──────────────┘        │
│         │                   │                   │                 │
│         └───────────────────┴───────────────────┘               │
│                              │                                   │
│                      ┌───────▼───────┐                          │
│                      │  DLP Plugin   │                          │
│                      │  (PII Mask)   │                          │
│                      └───────────────┘                          │
│                              │                                   │
│              ┌───────────────┼───────────────┐                   │
│              ▼               ▼               ▼                   │
│      ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐    │
│      │OpenTelemetry│ │  Structured │ │    Trace Context     │    │
│      │  Auto-Instr │ │   Logging   │ │   (Cloud Trace)      │    │
│      └─────────────┘ └─────────────┘ └─────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Vertex AI/Gemini│    │  Secret Manager   │    │  Cloud Trace    │
│                 │    │   (dlp-config)    │    │  (OpenTelemetry)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

**Note**: Orchestrator and Sub-Agent are Python modules within the same container. They coordinate locally and are NOT separate Cloud Run services. This is the recommended pattern for ADK agents.

---

## Quick Start

### 1. Prerequisites

```bash
# Set project ID
export PROJECT_ID="prj-dev-05022026"
export REGION="us-central1"

# Set default project
gcloud config set project $PROJECT_ID

# Authenticate
gcloud auth application-default login
```

### 2. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifact.googleapis.com \
  aiplatform.googleapis.com \
  dlp.googleapis.com \
  secretmanager.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com
```

### 3. Install Dependencies

```bash
cd /home/jayant/ulta/ulta-code
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Service Account Setup

### Create Service Account

```bash
gcloud iam service-accounts create adk-agents-sa \
  --display-name="ADK Agents Service Account" \
  --project=$PROJECT_ID
```

### Grant Required Roles

```bash
# Vertex AI (for Gemini models)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# DLP API
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/dlp.user"

# Secret Manager
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Cloud Trace (for OpenTelemetry)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudtrace.agent"

# Logging
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.writer"

# Metrics
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```

---

## Secret Manager Setup

### Create Secret for DLP Configuration

```bash
# Create the secret
echo '{
  "DLP_PROVIDER": "hybrid",
  "DLP_ACTION": "mask",
  "DLP_MASK_CHAR": "*",
  "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|PASSPORT_NUMBER|API_KEY|AUTH_TOKEN|DATE_OF_BIRTH|EMAIL_ADDRESS|PHONE_NUMBER|CREDIT_CARD_NUMBER|IP_ADDRESS",
  "DLP_SCAN_USER_MESSAGES": "true",
  "DLP_SCAN_LLM_REQUESTS": "true",
  "DLP_SCAN_LLM_RESPONSES": "true",
  "DLP_SCAN_TOOL_CALLS": "true",
  "DLP_SCAN_TOOL_RESULTS": "true",
  "DLP_AGENT_FILTER_MODE": "all",
  "DLP_ENABLED_AGENTS": "",
  "DLP_DISABLED_AGENTS": "",
  "DLP_FALLBACK_TO_REGEX": "true",
  "DLP_SKIP_ON_ERROR": "false",
  "DLP_ENABLE_EMAIL_DOMAIN_BYPASS": "true",
  "DLP_BYPASS_EMAIL_DOMAINS": "xyz.com",
  "DLP_BYPASS_EMAIL_SUBDOMAINS": "true"
}' | gcloud secrets create dlp-config \
  --data-file=- \
  --replication-policy="automatic" \
  --project=$PROJECT_ID

# Grant access to the service account
gcloud secrets add-iam-policy-binding dlp-config \
  --member="serviceAccount:adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=$PROJECT_ID
```

### Verify Secret

```bash
# View secret metadata
gcloud secrets describe dlp-config --project=$PROJECT_ID

# View secret value (be careful in production!)
gcloud secrets versions access latest --secret="dlp-config" --project=$PROJECT_ID
```

---

## Cloud Run Deployment

### Option 1: Quick Deploy (Recommended for Testing)

```bash
gcloud run deploy adk-agents \
  --source . \
  --region $REGION \
  --platform managed \
  --service-account adk-agents-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars "\
GOOGLE_CLOUD_PROJECT=$PROJECT_ID,\
GOOGLE_CLOUD_LOCATION=$REGION,\
GOOGLE_GENAI_USE_VERTEXAI=1,\
MODEL=gemini-2.5-flash,\
LOAD_FROM_SECRET_MANAGER=true,\
SECRETS_TO_LOAD=dlp-config,\
OTEL_EXPORTER_TYPE=gcp,\
OTEL_STRUCTURED_LOGS=true" \
  --min-instances 0 \
  --max-instances 10 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --allow-unauthenticated \
  --project $PROJECT_ID
```

### Option 2: Deploy via Cloud Build (Production)

First, create Artifact Registry repository:

```bash
gcloud artifacts repositories create adk-repo \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID
```

Update `cloudbuild.yaml`:

```yaml
steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: 
      - 'build'
      - '-t'
      - '${_REGION}-docker.pkg.dev/${PROJECT_ID}/adk-repo/adk-agents:${_VERSION}'
      - '.'
  
  # Push to Artifact Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: 
      - 'push'
      - '${_REGION}-docker.pkg.dev/${PROJECT_ID}/adk-repo/adk-agents:${_VERSION}'
  
  # Deploy to Cloud Run
  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'adk-agents'
      - '--image'
      - '${_REGION}-docker.pkg.dev/${PROJECT_ID}/adk-repo/adk-agents:${_VERSION}'
      - '--region'
      - '${_REGION}'
      - '--platform'
      - 'managed'
      - '--service-account'
      - 'adk-agents-sa@${PROJECT_ID}.iam.gserviceaccount.com'
      - '--set-env-vars'
      - 'GOOGLE_CLOUD_PROJECT=${PROJECTId},GOOGLE_CLOUD_LOCATION=${_REGION},GOOGLE_GENAI_USE_VERTEXAI=1,MODEL=gemini-2.5-flash,LOAD_FROM_SECRET_MANAGER=true,SECRETS_TO_LOAD=dlp-config,OTEL_EXPORTER_TYPE=gcp,OTEL_STRUCTURED_LOGS=true'
      - '--min-instances'
      - '0'
      - '--max-instances'
      - '10'
      - '--memory'
      - '1Gi'
      - '--cpu'
      - '1'
      - '--timeout'
      - '300'
      - '--allow-unauthenticated'

substitutions:
  _REGION: us-central1
  _VERSION: latest

options:
  logging: CLOUD_LOGGING_ONLY
```

Deploy:

```bash
gcloud builds submit --config=cloudbuild.yaml --project=$PROJECT_ID
```

---

## Environment Variables Reference

### Core Application

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Required | GCP Project ID |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | GCP Region |
| `GOOGLE_GENAI_USE_VERTEXAI` | `1` | Use Vertex AI |
| `MODEL` | `gemini-2.5-flash` | Gemini model name |
| `PORT` | `8080` | Server port |

### Secret Manager

| Variable | Default | Description |
|----------|---------|-------------|
| `LOAD_FROM_SECRET_MANAGER` | `false` | Enable secret loading |
| `SECRETS_TO_LOAD` | `dlp-config` | Comma-separated secret IDs |

### OpenTelemetry

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENABLED` | `true` | Enable telemetry |
| `OTEL_EXPORTER_TYPE` | `gcp` | Exporter: `gcp`, `otlp`, `console`, `none` |
| `OTEL_SERVICE_NAME` | `adk-agents` | Service name in traces |
| `OTEL_DEPLOYMENT_ENV` | `production` | Environment |
| `OTEL_STRUCTURED_LOGS` | `true` | JSON logs for production |

### LLM Pricing (Optional Overrides)

| Variable | Description |
|----------|-------------|
| `LLM_PRICE_FLASH_INPUT` | Flash model input price ($/1M tokens) |
| `LLM_PRICE_FLASH_OUTPUT` | Flash model output price ($/1M tokens) |

---

## Log Routing to Pub/Sub

### Create Topics

```bash
# Application logs
gcloud pubsub topics create app-logs-topic --project=$PROJECT_ID

# Auth failures
gcloud pubsub topics create auth-failures-topic --project=$PROJECT_ID

# Errors
gcloud pubsub topics create errors-topic --project=$PROJECT_ID

# Audit events
gcloud pubsub topics create audit-events-topic --project=$PROJECT_ID
```

### Create Log Sinks

```bash
# Application logs sink
gcloud logging sinks create app-logs-sink \
  pubsub.googleapis.com/projects/$PROJECT_ID/topics/app-logs-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="application"' \
  --project=$PROJECT_ID

# Auth failures sink
gcloud logging sinks create auth-failures-sink \
  pubsub.googleapis.com/projects/$PROJECT_ID/topics/auth-failures-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="auth_failure"' \
  --project=$PROJECT_ID

# Errors sink
gcloud logging sinks create errors-sink \
  pubsub.googleapis.com/projects/$PROJECT_ID/topics/errors-topic \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.log_category="error"' \
  --project=$PROJECT_ID

# Grant Pub/Sub publisher permissions to sink service accounts
for SINK in app-logs-sink auth-failures-sink errors-sink; do
  SINK_SA=$(gcloud logging sinks describe $SINK --project=$PROJECT_ID --format='value(writerIdentity)')
  TOPIC=$(gcloud logging sinks describe $SINK --project=$PROJECT_ID --format='value(destination)' | sed 's/.*\/\/.*\/topics\///')
  gcloud pubsub topics add-iam-policy-binding $TOPIC \
    --member="$SINK_SA" \
    --role="roles/pubsub.publisher" \
    --project=$PROJECT_ID
done
```

---

## Viewing Telemetry

### Cloud Trace

```bash
# Open Cloud Trace console
gcloud beta trace traces list --project=$PROJECT_ID
```

Or visit: `https://console.cloud.google.com/traces/list?project=$PROJECT_ID`

### Cloud Logging

```bash
# View recent logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agents" \
  --limit 50 \
  --project=$PROJECT_ID

# Stream logs
gcloud tail "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agents" \
  --project=$PROJECT_ID
```

### Telemetry Status Endpoint

```bash
# Get current telemetry config
curl https://YOUR-CLOUDRUN-URL/telemetry
```

### Interactive API Documentation

FastAPI provides built-in documentation available on Cloud Run:

```bash
# Swagger UI (interactive testing)
open https://YOUR-CLOUDRUN-URL.run.app/docs

# ReDoc (clean documentation)
open https://YOUR-CLOUDRUN-URL.run.app/redoc
```

Use Swagger UI to:
1. View all available endpoints
2. Test the `/invoke` endpoint interactively
3. See request/response schemas
4. Try different inputs without writing code

---

## LLM Cost Tracking

### How It Works

LLM costs are calculated dynamically using **LiteLLM's live pricing data**:

1. Auto-fetches pricing from LiteLLM's GitHub (community-maintained)
2. Caches for 24 hours
3. Falls back to defaults if fetch fails

### View Costs in Logs

Logs include cost estimation:

```
LLM Metrics: model=gemini-2.5-flash, tokens_in=1000, tokens_out=500, latency=1500.0ms, cost=$0.000157
```

### Custom Pricing (Optional)

```bash
# Override live pricing via environment variables
export LLM_PRICE_FLASH_INPUT=0.075   # $/1M tokens
export LLM_PRICE_FLASH_OUTPUT=0.30
```

---

## Local Development

### Setup

```bash
# Create .env file
cat > .env << 'EOF'
GOOGLE_CLOUD_PROJECT=prj-dev-05022026
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=1
MODEL=gemini-2.5-flash

# Disable Secret Manager for local dev (use .env values)
LOAD_FROM_SECRET_MANAGER=false

# OpenTelemetry (console for dev)
OTEL_ENABLED=true
OTEL_EXPORTER_TYPE=console
OTEL_SERVICE_NAME=adk-agents-dev
OTEL_DEPLOYMENT_ENV=development

# DLP Configuration (local)
DLP_PROVIDER=regex
DLP_ACTION=mask
DLP_INFO_TYPES=EMAIL_ADDRESS|PHONE_NUMBER|CREDIT_CARD_NUMBER
EOF

# Authenticate
gcloud auth application-default login

# Run locally
source venv/bin/activate
uvicorn adk_web_api.main:app --reload --port 8000
```

### Test Locally

#### Option 1: Interactive API Documentation (Recommended)

FastAPI provides an interactive Swagger UI for testing:

```bash
# Start the server
uvicorn adk_web_api.main:app --reload --port 8000

# Open in browser:
# - Swagger UI (interactive testing): http://localhost:8000/docs
# - ReDoc (clean documentation): http://localhost:8000/redoc
```

In Swagger UI (`/docs`):
1. Click on `/invoke` endpoint
2. Click "Try it out"
3. Enter your JSON request body
4. Click "Execute" to see the response

#### Option 2: Command Line Testing

```bash
# Health check / telemetry status
curl http://localhost:8000/telemetry

# Test agent invocation
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Google Cloud?"}'

# Test DLP masking
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "My email is test@example.com and SSN is 123-45-6789"}'
```

### Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/docs` | GET | Swagger UI - interactive API testing |
| `/redoc` | GET | ReDoc - clean API documentation |
| `/telemetry` | GET | OpenTelemetry configuration status |
| `/invoke` | POST | Main agent invocation endpoint |

---

## Troubleshooting

### Cloud Run Won't Start

```bash
# Check logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agents" \
  --limit 10 --project $PROJECT_ID

# Common issues:
# 1. Missing IAM roles - verify service account permissions
# 2. Secret not found - check secret exists and SA has access
# 3. Vertex AI not enabled - run: gcloud services enable aiplatform.googleapis.com
```

### Secret Manager Issues

```bash
# Verify secret exists
gcloud secrets describe dlp-config --project=$PROJECT_ID

# Check service account access
gcloud secrets get-iam-policy dlp-config --project=$PROJECT_ID

# Test access manually
gcloud secrets versions access latest --secret="dlp-config" --project=$PROJECT_ID
```

### Traces Not Appearing

```bash
# Verify Cloud Trace API is enabled
gcloud services list --enabled --project=$PROJECT_ID | grep trace

# Check service account permissions
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:adk-agents-sa"
```

### DLP Not Working

```bash
# Check DLP API is enabled
gcloud services list --enabled --project=$PROJECT_ID | grep dlp

# Test DLP locally
python -c "
from adk_web_api.dlp_plugin import create_dlp_plugin
from adk_web_api.dlp_service import DLPService

plugin = create_dlp_plugin(profile='basic')
service = DLPService(plugin.settings)
result = service.scan('My email is test@example.com')
print(f'Original: {result.original_text}')
print(f'Processed: {result.processed_text}')
"
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Google Cloud project created
- [ ] All APIs enabled
- [ ] Service account created with all required roles
- [ ] Secret `dlp-config` created in Secret Manager
- [ ] Local tests pass

### Post-Deployment

- [ ] Cloud Run service is running
- [ ] `/telemetry` endpoint returns valid JSON
- [ ] `/invoke` endpoint responds correctly
- [ ] Cloud Trace shows traces
- [ ] Cloud Logging shows structured logs
- [ ] Log sinks configured (if using Pub/Sub routing)

---

## Cost Estimates

### Cloud Run

| Resource | Cost |
|----------|------|
| Idle (min-instances=0) | $0 |
| Requests | ~$5-20 per 1M |
| Memory (1GB) | ~$0.10/GB-hour |

### Vertex AI (Gemini)

| Model | Input | Output |
|-------|-------|--------|
| gemini-2.5-flash | $0.075/1M tokens | $0.30/1M tokens |
| gemini-2.5-pro | $1.25/1M tokens | $5.00/1M tokens |

### Secret Manager

| Usage | Cost |
|-------|------|
| First 6 versions | Free |
| After free tier | ~$0.03/secret version/month |
| Access operations | ~$0.03/10,000 operations |

### DLP API

| Usage | Cost |
|-------|------|
| First 1,000 items/month | Free |
| After free tier | ~$0.0005/1,000 items |

---

## Related Documentation

- [TELEMETRY_CHANGES.md](TELEMETRY_CHANGES.md) - OpenTelemetry implementation details
- [adk_web_api/DLP_SETUP_GUIDE.md](adk_web_api/DLP_SETUP_GUIDE.md) - DLP configuration details
