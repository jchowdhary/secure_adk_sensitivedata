# ADK Agents with FastAPI

A simple ADK agents implementation using FastAPI's `getfastapi` method with Vertex AI enabled. Includes an orchestrator agent and a sub-agent in separate folders.

## Project Structure

```
ulta-code/
├── adk_web_api/
│   ├── __init__.py
│   └── main.py          # FastAPI app using getfastapi
├── orchestrator/
│   ├── __init__.py
│   └── main.py          # Orchestrator agent
├── sub_agent/
│   ├── __init__.py
│   └── main.py          # Sub agent
├── Dockerfile
├── cloudbuild.yaml
├── requirements.txt
└── README.md
```

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Authenticate with Google Cloud (for Vertex AI):
```bash
gcloud auth application-default login
```

## Running Locally

### Option 1: Using ADK Web
```bash
adk web
```

### Option 2: Using ADK API Server
```bash
adk api-server --port 8000
```

### Option 3: Direct FastAPI run
```bash
uvicorn adk_web_api.main:app --reload --host 0.0.0.0 --port 8000
```

Access the API at: http://localhost:8000

## Cloud Run Deployment

Ensure you have the Google Cloud SDK installed and authenticated:

1. Build and deploy using Cloud Build:
```bash
gcloud builds submit --config cloudbuild.yaml
```

2. Or manually:
```bash
# Build the Docker image
gcloud builds submit --tag gcr.io/PROJECT-ID/adk-agents

# Deploy to Cloud Run
gcloud run deploy adk-agents \
  --image gcr.io/PROJECT-ID/adk-agents \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

Replace `PROJECT-ID` with your Google Cloud project ID.

## Agents Description

### Orchestrator Agent
- Manager agent that coordinates tasks
- Determines when to delegate to sub-agents
- Provides consolidated responses

### Sub Agent
- Handles specialized delegated tasks
- Provides focused, detailed responses
- Works in coordination with the orchestrator