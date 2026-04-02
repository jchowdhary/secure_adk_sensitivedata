# Google Cloud DLP Setup Guide

## 1. Python Modules Required

### Option A: Regex-based DLP (No additional modules)
```bash
# Already works! No installation needed.
# Uses built-in regex patterns.
```

### Option B: Google Cloud DLP (Enterprise)
```bash
# Activate virtual environment
cd /home/jayant/ulta/ulta-code
source venv/bin/activate

# Install DLP module
pip install google-cloud-dlp>=3.15.0

# Or use requirements file
pip install -r requirements-dlp.txt
```

## 2. Google Cloud Credentials Setup

### Step-by-Step Guide to Create Service Account

#### Step 1: Go to Google Cloud Console
1. Open: https://console.cloud.google.com/
2. Select your project: `prj-dev-05022026` (from your .env file)

#### Step 2: Create Service Account
1. Navigate to: **IAM & Admin** → **Service Accounts**
   - Direct link: https://console.cloud.google.com/iam-admin/serviceaccounts?project=prj-dev-05022026

2. Click **"Create Service Account"**
   - **Name**: `adk-dlp-service-account`
   - **Description**: `Service account for ADK DLP integration`
   - Click **"Create and Continue"**

#### Step 3: Grant Permissions
Add the following roles:

| Role | Purpose |
|------|---------|
| `DLP Service Agent` (`roles/dlp.serviceAgent`) | **Required** - Access DLP API |
| `DLP User` (`roles/dlp.user`) | **Required** - Call DLP API |
| `DLP Jobs Editor` (`roles/dlp.jobsEditor`) | Optional - Create/manage DLP jobs |
| `Service Usage Consumer` (`roles/serviceusage.serviceUsageConsumer`) | Required for API usage |

**How to add roles:**
1. In the "Grant this service account access to project" section
2. Search for "DLP" in the role filter
3. Select `DLP Service Agent` and `DLP User`
4. Click **"Continue"**
5. Click **"Done"**

#### Step 4: Create and Download JSON Key
1. Click on the newly created service account
2. Go to **"Keys"** tab
3. Click **"Add Key"** → **"Create new key"**
4. Select **"JSON"** format
5. Click **"Create"**
6. **Important**: The JSON file will download automatically. Save it securely!

#### Step 5: Store Credentials Securely
```bash
# Create a secure directory (outside git repo)
mkdir -p ~/.config/gcloud/credentials

# Move the downloaded JSON file
mv ~/Downloads/adk-dlp-service-account-*.json ~/.config/gcloud/credentials/adk-dlp-credentials.json

# Set restrictive permissions
chmod 600 ~/.config/gcloud/credentials/adk-dlp-credentials.json
```

#### Step 6: Configure Environment Variable
Add to your `.env` file:

```bash
# Edit .env file
nano /home/jayant/ulta/ulta-code/.env
```

Add this line:
```env
GOOGLE_APPLICATION_CREDENTIALS=/home/jayant/.config/gcloud/credentials/adk-dlp-credentials.json
```

## 3. Enable DLP API in Google Cloud Console

### Step 1: Enable the API
1. Go to: **APIs & Services** → **Library**
   - Direct link: https://console.cloud.google.com/apis/library?project=prj-dev-05022026

2. Search for: **"Cloud Data Loss Prevention (DLP) API"**

3. Click on it and press **"Enable"** button

### Step 2: Verify API is Enabled
1. Go to: **APIs & Services** → **Enabled APIs and Services**
   - Direct link: https://console.cloud.google.com/apis/enabled?project=prj-dev-05022026

2. Search for "DLP" - you should see it listed

### Alternative: Enable via gcloud CLI
```bash
# Install gcloud if not already installed
# Then enable the API:
gcloud services enable dlp.googleapis.com --project=prj-dev-05022026
```

## 4. Should You Keep the Initial PII Masking Plugin?

### Recommendation: **NO** - Use DLP Instead

Here's why:

| Aspect | PII Masking Plugin | DLP Plugin |
|--------|-------------------|------------|
| **Detection** | 6 basic types | 100+ info types |
| **Accuracy** | ~60-70% | ~95%+ (with Google Cloud) |
| **Configurability** | Hardcoded patterns | Configurable via env/profiles |
| **Tool Call Support** | ✅ Yes | ✅ Yes |
| **Google Cloud Integration** | ❌ No | ✅ Yes |
| **Compliance Ready** | ❌ No | ✅ HIPAA/PCI/GDPR |

### Migration Path

#### Option 1: Complete Replacement (Recommended)
```python
# In adk_web_api/main.py

# OLD:
from pii_masking_plugin import create_pii_masking_plugin
pii_plugin = create_pii_masking_plugin()

# NEW:
from dlp_plugin import create_dlp_plugin
# Use basic profile for same functionality (regex-based)
dlp_plugin = create_dlp_plugin(profile="basic")

# OR upgrade to Google Cloud DLP for better accuracy:
dlp_plugin = create_dlp_plugin(profile="standard")
```

#### Option 2: Use Both (Defense-in-Depth) - Overkill but Possible
```python
# This provides two layers of protection
# PII plugin runs first (fast), DLP runs second (more accurate)

runner = Runner(
    app_name="OrchestratorAPI",
    agent=agents["orchestrator"],
    session_service=InMemorySessionService(),
    artifact_service=InMemoryArtifactService(),
    memory_service=InMemoryMemoryService(),
    auto_create_session=True,
    plugins=[
        create_pii_masking_plugin(),  # Fast, first line
        create_dlp_plugin(profile="standard"),  # More accurate
    ]
)
```

**Note**: Using both is redundant and will slow down your application. **Not recommended.**

#### Option 3: Gradual Migration
```python
# Phase 1: Use DLP with regex (same as PII plugin)
dlp_plugin = create_dlp_plugin(profile="basic")

# Phase 2: Switch to Google Cloud DLP (after testing)
dlp_plugin = create_dlp_plugin(profile="standard")

# Phase 3: Enterprise with full features
dlp_plugin = create_dlp_plugin(profile="enterprise")
```

## 5. Complete .env Configuration

Update your `/home/jayant/ulta/ulta-code/.env` file:

```env
# Existing configuration
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=prj-dev-05022026
GOOGLE_CLOUD_LOCATION=us-central1
MODEL=gemini-2.5-flash

# DLP Configuration
DLP_PROVIDER=regex              # Start with regex, change to "google_cloud" later
DLP_ACTION=mask                 # Options: mask, redact, replace, hash, alert
DLP_MASK_CHAR=*

# Info types to detect (comma-separated)
DLP_INFO_TYPES=EMAIL_ADDRESS,PHONE_NUMBER,US_SOCIAL_SECURITY_NUMBER,CREDIT_CARD_NUMBER,IP_ADDRESS

# Scopes (what to scan)
DLP_SCAN_USER_MESSAGES=true
DLP_SCAN_LLM_REQUESTS=true
DLP_SCAN_LLM_RESPONSES=true
DLP_SCAN_TOOL_CALLS=true
DLP_SCAN_TOOL_RESULTS=true

# Google Cloud DLP (required for google_cloud provider)
GOOGLE_APPLICATION_CREDENTIALS=/home/jayant/.config/gcloud/credentials/adk-dlp-credentials.json

# Error handling
DLP_FALLBACK_TO_REGEX=true      # Fallback to regex if Google Cloud fails
DLP_SKIP_ON_ERROR=false         # If false, let text through unmasked on error
```

## 6. Testing Your Setup

### Test 1: Regex-based DLP (Works immediately)
```bash
# No additional setup needed
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
python -c "
from adk_web_api.dlp_plugin import create_dlp_plugin
from adk_web_api.dlp_service import DLPService

dlp_plugin = create_dlp_plugin(profile='basic')
service = DLPService(dlp_plugin.settings)

# Test detection
result = service.scan('My email is test@example.com and SSN is 123-45-6789')
print(f'Original: {result.original_text}')
print(f'Processed: {result.processed_text}')
print(f'Findings: {len(result.findings)}')
"
```

### Test 2: Google Cloud DLP (After setup)
```bash
# After installing google-cloud-dlp and setting credentials
python -c "
from adk_web_api.dlp_plugin import create_dlp_plugin
from adk_web_api.dlp_service import DLPService

dlp_plugin = create_dlp_plugin(profile='standard')
service = DLPService(dlp_plugin.settings)

# Test detection
result = service.scan('Contact John Smith at john@example.com, phone (555) 123-4567')
print(f'Original: {result.original_text}')
print(f'Processed: {result.processed_text}')
print(f'Findings: {len(result.findings)}')
print(f'Provider: {result.provider_used}')
"
```

## 7. Cost Considerations

### Google Cloud DLP Pricing
- **Free tier**: $0 for first 1,000 inspected items per month
- **After free tier**: ~$0.0005 per 1,000 inspected items
- **Deidentify**: ~$1.00 per 1,000 items

### Cost Optimization Tips
1. Use `DLPProvider.REGEX` for development
2. Use `DLPProvider.HYBRID` for production (Google Cloud with regex fallback)
3. Set `max_bytes_per_request` to limit request size
4. Batch processing when possible

## 8. Quick Start Commands

```bash
# 1. Install DLP module (if using Google Cloud DLP)
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
pip install google-cloud-dlp

# 2. Enable DLP API (via gcloud)
gcloud services enable dlp.googleapis.com --project=prj-dev-05022026

# 3. Create service account and download key (via console - see steps above)

# 4. Update .env file with credentials path

# 5. Test your setup
python -m adk_web_api.main
```

## Summary Checklist

- [ ] Install `google-cloud-dlp` (only if using Google Cloud DLP)
- [ ] Create service account in Google Cloud Console
- [ ] Grant `DLP Service Agent` and `DLP User` roles
- [ ] Download JSON credentials
- [ ] Store credentials securely
- [ ] Update `.env` with `GOOGLE_APPLICATION_CREDENTIALS` path
- [ ] Enable DLP API in Google Cloud Console
- [ ] Update `main.py` to use DLP plugin instead of PII plugin
- [ ] Test with regex profile first
- [ ] Test with Google Cloud DLP profile after setup works