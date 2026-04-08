# Google Secret Manager Integration Guide

## Overview

This guide explains how to use Google Cloud Secret Manager to dynamically load environment variables, enabling configuration updates without redeploying to Cloud Run.

## Why Secret Manager?

| Problem | Solution |
|---------|----------|
| Changing DLP config requires redeployment | Update secret → restart pod (no rebuild) |
| Sensitive data in Dockerfile/env vars | Secrets stored securely in GCP |
| No version control for config changes | Secret versions track all changes |
| Hard to audit config changes | Cloud Audit Logs for secret access |

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│   Cloud Run         │     │   Secret Manager     │
│                     │     │                      │
│  ┌───────────────┐  │     │  ┌────────────────┐  │
│  │  main.py      │  │     │  │  dlp-config    │  │
│  │               │  │────▶│  │  (JSON)        │  │
│  │  Secret       │  │     │  └────────────────┘  │
│  │  Manager      │  │     │                      │
│  │  Loader       │  │     │  ┌────────────────┐  │
│  └───────────────┘  │     │  │  adk-config    │  │
│         │           │     │  │  (JSON)        │  │
│         ▼           │     │  └────────────────┘  │
│  ┌───────────────┐  │     │                      │
│  │  os.environ   │  │     │  ┌────────────────┐  │
│  │  (DLP_*)      │  │     │  │  api-keys      │  │
│  └───────────────┘  │     │  └────────────────┘  │
└─────────────────────┘     └──────────────────────┘
```

## Prerequisites

1. Google Cloud Project with Secret Manager API enabled
2. Service account with `roles/secretmanager.secretAccessor` role
3. `google-cloud-secret-manager` Python package installed

## Step-by-Step Setup

### Step 1: Install Required Package

```bash
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
pip install google-cloud-secret-manager
```

### Step 2: Enable Secret Manager API

```bash
# Enable the API
gcloud services enable secretmanager.googleapis.com --project=prj-dev-05022026

# Verify it's enabled
gcloud services list --project=prj-dev-05022026 | grep secretmanager
```

### Step 3: Create the DLP Configuration Secret

#### Option A: Using gcloud CLI

```bash
# Create the secret
gcloud secrets create dlp-config \
    --replication-policy="automatic" \
    --project=prj-dev-05022026

# Add the secret version with DLP configuration
cat <<EOF | gcloud secrets versions add dlp-config --data-file=- --project=prj-dev-05022026
{
    "DLP_PROVIDER": "google_cloud",
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
    "DLP_SKIP_ON_ERROR": "false"
}
EOF
```

#### Option B: Using Google Cloud Console

1. Go to: **Security** → **Secret Manager**
   - Direct link: https://console.cloud.google.com/security/secret-manager?project=prj-dev-05022026

2. Click **"Create Secret"**

3. Fill in the form:
   - **Name**: `dlp-config`
   - **Secret value**: Paste the JSON below

```json
{
    "DLP_PROVIDER": "google_cloud",
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
    "DLP_SKIP_ON_ERROR": "false"
}
```

4. Click **"Create Secret"**

### Step 4: Grant Permissions to Service Account

Your Cloud Run service account needs permission to access secrets.

```bash
# Get your Cloud Run service account email
# (Replace with your actual service account)
SERVICE_ACCOUNT="YOUR_SERVICE_ACCOUNT@prj-dev-05022026.iam.gserviceaccount.com"

# Grant Secret Manager accessor role
gcloud secrets add-iam-policy-binding dlp-config \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=prj-dev-05022026
```

Or via Console:
1. Go to **Secret Manager** → **dlp-config**
2. Click **"Permissions"** tab
3. Click **"Add Principal"**
4. Add your service account with role: **Secret Manager Secret Accessor**

### Step 5: Configure Cloud Run Environment Variables

In Cloud Run, set these environment variables to enable Secret Manager loading:

```bash
# Via gcloud
gcloud run services update YOUR_SERVICE_NAME \
    --set-env-vars="LOAD_SECRETS_FROM_SECRET_MANAGER=true" \
    --set-env-vars="SECRETS_TO_LOAD=dlp-config" \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=prj-dev-05022026" \
    --region=us-central1 \
    --project=prj-dev-05022026
```

Or via Console:
1. Go to **Cloud Run** → Your Service → **Edit & Deploy New Revision**
2. Under **Variables & Secrets** → **Environment Variables**, add:
   - `LOAD_SECRETS_FROM_SECRET_MANAGER` = `true`
   - `SECRETS_TO_LOAD` = `dlp-config` (comma-separated for multiple)
   - `GOOGLE_CLOUD_PROJECT` = `prj-dev-05022026`

### Step 6: Verify Secret Access (Local Testing)

```bash
# Set environment for local testing
export GOOGLE_CLOUD_PROJECT=prj-dev-05022026
export LOAD_SECRETS_FROM_SECRET_MANAGER=true
export SECRETS_TO_LOAD=dlp-config

# Run the application
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
python -m adk_web_api.main
```

## Updating Configuration Without Redeployment

### Update the Secret Value

```bash
# Create a new version with updated config
cat <<EOF | gcloud secrets versions add dlp-config --data-file=- --project=prj-dev-05022026
{
    "DLP_PROVIDER": "hybrid",
    "DLP_ACTION": "redact",
    "DLP_MASK_CHAR": "*",
    "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|EMAIL_ADDRESS|PHONE_NUMBER",
    "DLP_SCAN_USER_MESSAGES": "true",
    "DLP_SCAN_LLM_REQUESTS": "true",
    "DLP_SCAN_LLM_RESPONSES": "true",
    "DLP_SCAN_TOOL_CALLS": "true",
    "DLP_SCAN_TOOL_RESULTS": "true",
    "DLP_AGENT_FILTER_MODE": "allowlist",
    "DLP_ENABLED_AGENTS": "orchestrator|sub_agent",
    "DLP_DISABLED_AGENTS": "",
    "DLP_FALLBACK_TO_REGEX": "true",
    "DLP_SKIP_ON_ERROR": "false"
}
EOF
```

### Trigger Restart (No Rebuild Needed)

The secret is loaded at startup, so you need to restart the Cloud Run instance:

```bash
# Option 1: Force a new revision (no code change, just restart)
gcloud run services update YOUR_SERVICE_NAME \
    --no-cpu-throttling \
    --region=us-central1 \
    --project=prj-dev-05022026

# Option 2: Use Cloud Run's built-in secret mounting
# This reloads secrets automatically without restart
```

## Secret Configuration Examples

### Enterprise Profile (Google Cloud DLP)

```json
{
    "DLP_PROVIDER": "google_cloud",
    "DLP_ACTION": "mask",
    "DLP_MASK_CHAR": "*",
    "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|PASSPORT_NUMBER|API_KEY|AUTH_TOKEN|DATE_OF_BIRTH|EMAIL_ADDRESS|PHONE_NUMBER|CREDIT_CARD_NUMBER|IP_ADDRESS|PERSON_NAME|LOCATION|US_BANK_ACCOUNT_NUMBER|IBAN_CODE|MEDICAL_TERM",
    "DLP_SCAN_USER_MESSAGES": "true",
    "DLP_SCAN_LLM_REQUESTS": "true",
    "DLP_SCAN_LLM_RESPONSES": "true",
    "DLP_SCAN_TOOL_CALLS": "true",
    "DLP_SCAN_TOOL_RESULTS": "true",
    "DLP_AGENT_FILTER_MODE": "all",
    "DLP_ENABLED_AGENTS": "",
    "DLP_DISABLED_AGENTS": "",
    "DLP_FALLBACK_TO_REGEX": "true",
    "DLP_SKIP_ON_ERROR": "false"
}
```

### Hybrid Profile

```json
{
    "DLP_PROVIDER": "hybrid",
    "DLP_ACTION": "mask",
    "DLP_MASK_CHAR": "*",
    "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|EMAIL_ADDRESS|PHONE_NUMBER|PERSON_NAME|LOCATION",
    "DLP_SCAN_USER_MESSAGES": "true",
    "DLP_SCAN_LLM_REQUESTS": "true",
    "DLP_SCAN_LLM_RESPONSES": "true",
    "DLP_SCAN_TOOL_CALLS": "true",
    "DLP_SCAN_TOOL_RESULTS": "true",
    "DLP_AGENT_FILTER_MODE": "allowlist",
    "DLP_ENABLED_AGENTS": "orchestrator|sub_agent",
    "DLP_DISABLED_AGENTS": "",
    "DLP_FALLBACK_TO_REGEX": "true",
    "DLP_SKIP_ON_ERROR": "false"
}
```

### Basic Profile (Regex Only - Free)

```json
{
    "DLP_PROVIDER": "regex",
    "DLP_ACTION": "mask",
    "DLP_MASK_CHAR": "*",
    "DLP_INFO_TYPES": "EMAIL_ADDRESS|PHONE_NUMBER|US_SOCIAL_SECURITY_NUMBER|CREDIT_CARD_NUMBER",
    "DLP_SCAN_USER_MESSAGES": "true",
    "DLP_SCAN_LLM_REQUESTS": "true",
    "DLP_SCAN_LLM_RESPONSES": "true",
    "DLP_SCAN_TOOL_CALLS": "true",
    "DLP_SCAN_TOOL_RESULTS": "true",
    "DLP_AGENT_FILTER_MODE": "all",
    "DLP_ENABLED_AGENTS": "",
    "DLP_DISABLED_AGENTS": "",
    "DLP_FALLBACK_TO_REGEX": "true",
    "DLP_SKIP_ON_ERROR": "false"
}
```

## Multiple Secrets

You can split configuration into multiple secrets:

```bash
# Set multiple secrets to load
SECRETS_TO_LOAD=dlp-config,adk-config,api-keys
```

### dlp-config.json
```json
{
    "DLP_PROVIDER": "google_cloud",
    "DLP_ACTION": "mask",
    ...
}
```

### adk-config.json
```json
{
    "MODEL": "gemini-2.5-flash",
    "GOOGLE_CLOUD_LOCATION": "us-central1"
}
```

### api-keys.json
```json
{
    "GOOGLE_API_KEY": "your-api-key",
    "THIRD_PARTY_API_KEY": "another-key"
}
```

## Testing Locally

### Without Secret Manager (Using .env)

```bash
# Just use .env file
python -m adk_web_api.main
```

### With Secret Manager (Local)

```bash
# Authenticate with gcloud
gcloud auth application-default login

# Enable Secret Manager loading
export LOAD_SECRETS_FROM_SECRET_MANAGER=true
export GOOGLE_CLOUD_PROJECT=prj-dev-05022026

# Run
python -m adk_web_api.main
```

## Troubleshooting

### Error: "Secret 'dlp-config' not found"

```bash
# Check if secret exists
gcloud secrets list --project=prj-dev-05022026

# Create if missing
gcloud secrets create dlp-config --replication-policy="automatic"
```

### Error: "Permission denied for secret"

```bash
# Check your service account
gcloud auth list

# Grant permissions
gcloud secrets add-iam-policy-binding dlp-config \
    --member="user:YOUR_EMAIL@example.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Error: "google-cloud-secret-manager not installed"

```bash
pip install google-cloud-secret-manager
```

### Secret not loading at startup

1. Verify `LOAD_SECRETS_FROM_SECRET_MANAGER=true` is set
2. Check logs for errors during startup
3. Verify service account has `secretmanager.secretAccessor` role

## Security Best Practices

1. **Use separate secrets for different environments** (dev, staging, prod)
2. **Enable Secret versioning** - old versions are retained for rollback
3. **Use IAM conditions** to restrict access by service account
4. **Enable Cloud Audit Logs** to track secret access
5. **Never log secret values** - the loader only logs keys, not values
6. **Use automatic replication** for high availability

## Quick Reference Commands

```bash
# List all secrets
gcloud secrets list --project=prj-dev-05022026

# View secret metadata (not value)
gcloud secrets describe dlp-config --project=prj-dev-05022026

# Access secret value (be careful!)
gcloud secrets versions access latest --secret=dlp-config --project=prj-dev-05022026

# Add new version
gcloud secrets versions add dlp-config --data-file=config.json

# Disable old version
gcloud secrets versions disable 1 --secret=dlp-config

# Delete secret (careful!)
gcloud secrets delete dlp-config --project=prj-dev-05022026
```

## Cost

Secret Manager pricing:
- **Free tier**: 6 secret versions per month, 10,000 access operations
- **Storage**: $0.06 per secret version per month
- **Access operations**: $0.03 per 10,000 operations

For typical usage with 1-2 secrets, cost is negligible (under $1/month).
