# Parameter Manager Integration Guide

## What This Guide Covers

This project is moving configuration out of application code and into Google Cloud Parameter Manager.

Important note about naming in the codebase:

- [`secret_manager.py`](/home/jayant/ulta/ulta-code/adk_web_api/secret_manager.py) still uses legacy names like `SecretManagerLoader`
- The implementation itself is already using `google.cloud.parametermanager_v1`
- [`main.py`](/home/jayant/ulta/ulta-code/adk_web_api/main.py) has the startup-loading block present, but it is currently commented out

So the current design is:

1. `.env` is loaded first for local development
2. Parameter Manager values can optionally be loaded at startup
3. Loaded values are written into `os.environ`
4. Modules like [`dlp_config.py`](/home/jayant/ulta/ulta-code/adk_web_api/dlp_config.py) read from those environment variables

## Current Code Behavior

### `secret_manager.py`

[`secret_manager.py`](/home/jayant/ulta/ulta-code/adk_web_api/secret_manager.py) does the following:

- Creates a `ParameterManagerClient`
- Reads parameter versions from:
  - `projects/{project}/locations/global/parameters/{parameter_id}/versions/{version}`
- Default version is `"new"`
- Supports loading:
  - a single raw parameter value
  - a JSON parameter payload
  - multiple parameters at startup
- Can set environment variables from JSON key/value pairs
- Can optionally filter to only keys starting with a prefix like `DLP_`

Main helper functions:

- `load_secrets_at_startup(secret_ids=...)`
- `load_dlp_config_from_secret(secret_id="dlp-config")`

Despite the names, these helpers are loading from Parameter Manager, not Secret Manager.

### `main.py`

[`main.py`](/home/jayant/ulta/ulta-code/adk_web_api/main.py) currently:

- loads `.env`
- contains a commented block that can load parameters before the rest of the app starts
- prefers these environment variables when enabled:
  - `LOAD_FROM_PARAMETER_MANAGER=true`
  - `PARAMETER_TO_LOAD=dlp-config`
  - `GOOGLE_CLOUD_PROJECT=<project-id>`
- also supports the older compatibility names:
  - `LOAD_SECRETS_FROM_SECRET_MANAGER=true`
  - `SECRETS_TO_LOAD=dlp-config`

If you want Parameter Manager loading to actually happen at startup, you must uncomment that block.

### `dlp_config.py`

[`dlp_config.py`](/home/jayant/ulta/ulta-code/adk_web_api/dlp_config.py) builds `DLPSettings` from environment variables.

That means Parameter Manager is a good fit here: store a JSON parameter with keys like `DLP_PROVIDER`, `DLP_ACTION`, `DLP_INFO_TYPES`, and load them into `os.environ` before the DLP plugin is created.

## Recommended Flow

Use one JSON parameter such as `dlp-config` whose payload contains all `DLP_*` values.

At startup:

1. `.env` is loaded first
2. Parameter Manager overrides those values
3. `create_dlp_plugin(profile="hybrid")` runs with the updated environment

This lets you change runtime configuration without hardcoding it in Python.

## Prerequisites

You need:

- a Google Cloud project
- Parameter Manager enabled in that project
- a runtime identity or local identity with Parameter Manager read access
- the Python package `google-cloud-parametermanager`

## Python Dependency

Install the package used by the current implementation:

```bash
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
pip install google-cloud-parametermanager
```

### Enable the API & Grant Permissions
```bash
# Enable the Parameter Manager API
gcloud services enable parametermanager.googleapis.com --project=prj-dev-05022026

# Grant your service account the Parameter Accessor role
gcloud projects add-iam-policy-binding prj-dev-05022026 \
    --member="serviceAccount:YOUR_SERVICE_ACCOUNT@prj-dev-05022026.iam.gserviceaccount.com" \
    --role="roles/parametermanager.parameterAccessor"
```

### Create your Paramter
Parameter Manager separates the format definition from the version payload. Create a global parameter formatted for JSON:
```bash
# 1. Create the empty parameter container
gcloud beta parametermanager parameters create dlp-config \
    --location=global \
    --parameter-format=json \
    --project=prj-dev-05022026

# 2. Add your JSON configuration as the 'latest' version
cat dlp_config.json | gcloud beta parametermanager parameters versions create latest \
    --parameter=dlp-config \
    --location=global \
    --payload-data=- \
    --project=prj-dev-05022026
```


## Parameter Structure

Create a parameter named `dlp-config` with a JSON payload like this:

```json
{
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
  "DLP_BYPASS_EMAIL_DOMAINS": "ulta.com",
  "DLP_BYPASS_EMAIL_SUBDOMAINS": "true"
}
```

Notes:

- `DLP_INFO_TYPES` is pipe-delimited because that is what `DLPSettings.from_env()` expects
- boolean values should be stored as strings like `"true"` or `"false"`
- any JSON key loaded by `set_env_from_secret()` becomes an environment variable

## Enable Startup Loading In `main.py`

The startup integration is already written in [`main.py`](/home/jayant/ulta/ulta-code/adk_web_api/main.py), but commented.

To use Parameter Manager:

1. Uncomment the startup-loading block near the top of `main.py`
2. Keep it before imports that depend on DLP env vars
3. Set the required environment variables in Cloud Run or locally

The code path is intended to work like this:

```python
load_from_parameter_manager = (
    os.getenv("LOAD_FROM_PARAMETER_MANAGER")
    or os.getenv("LOAD_SECRETS_FROM_SECRET_MANAGER", "false")
).lower() == "true"

if load_from_parameter_manager:
    from .secret_manager import load_secrets_at_startup

    parameter_to_load = os.getenv("PARAMETER_TO_LOAD", "").strip()
    parameters_to_load_str = (
        os.getenv("PARAMETERS_TO_LOAD")
        or os.getenv("SECRETS_TO_LOAD", "")
    )
    parameters_to_load = [s.strip() for s in parameters_to_load_str.split(",") if s.strip()]

    if parameter_to_load:
        parameters_to_load = [parameter_to_load]

    if not parameters_to_load:
        parameters_to_load = ["dlp-config"]

    load_secrets_at_startup(secret_ids=parameters_to_load)
```

For the simplest setup, use `PARAMETER_TO_LOAD=dlp-config`.
That single parameter can contain all your JSON keys, and all of them will be loaded into `os.environ`.

## Local Run

### Verify
```bash
python -c "
from adk_web_api.secret_manager import SecretManagerLoader
import json
import os

print('🚀 Initializing Loader...')
try:
    loader = SecretManagerLoader()
    
    print('\n📥 Fetching JSON payload for \'dlp-config\'...')
    config = loader.load_secret_as_json('dlp-config')
    print(json.dumps(config, indent=2))
    
    print('\n⚙️ Loading values into Environment Variables...')
    vars_set = loader.set_env_from_secret('dlp-config')
    print(f'✅ Successfully loaded {len(vars_set)} variables into os.environ')
    
    print('\n🔍 Verifying specific fetched values:')
    print(f'  -> DLP_PROVIDER: {os.environ.get(\"DLP_PROVIDER\")}')
    print(f'  -> DLP_ACTION: {os.environ.get(\"DLP_ACTION\")}')
    print(f'  -> DLP_INFO_TYPES: {os.environ.get(\"DLP_INFO_TYPES\")}')

except Exception as e:
    print(f'\n❌ Error occurred: {e}')
"
```

### Without Parameter Manager

Use only `.env`:

```bash
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
python -m adk_web_api.main
```

### With Parameter Manager

Authenticate locally with Application Default Credentials, then:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export LOAD_FROM_PARAMETER_MANAGER=true
export PARAMETER_TO_LOAD=dlp-config

cd /home/jayant/ulta/ulta-code
source venv/bin/activate
python -m adk_web_api.main
```

## Cloud Run Environment Variables

Set these in Cloud Run:

```bash
LOAD_FROM_PARAMETER_MANAGER=true
PARAMETER_TO_LOAD=dlp-config
GOOGLE_CLOUD_PROJECT=your-project-id
```

Optional:

```bash
PARAMETERS_TO_LOAD=dlp-config,adk-config
DEFAULT_SECRETS=dlp-config
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

Notes:

- On Cloud Run, Application Default Credentials are usually preferred over key files
- `DEFAULT_SECRETS` is only used when no explicit `secret_ids` are passed into `load_all_secrets()`
- this app prefers `PARAMETER_TO_LOAD` or `PARAMETERS_TO_LOAD` in the startup flow
- legacy `SECRETS_TO_LOAD` still works for backward compatibility

## Multiple Parameters

You can load multiple JSON parameters:

```bash
PARAMETERS_TO_LOAD=dlp-config,adk-config,api-keys
```

Examples:

### `dlp-config`

```json
{
  "DLP_PROVIDER": "google_cloud",
  "DLP_ACTION": "mask"
}
```

### `adk-config`

```json
{
  "MODEL": "gemini-2.5-flash",
  "GOOGLE_CLOUD_LOCATION": "us-central1"
}
```

### `api-keys`

```json
{
  "GOOGLE_API_KEY": "your-api-key"
}
```

## Operational Notes

### Versioning

The loader defaults to version `"new"`:

```python
loader.load_secret("dlp-config", version="new")
```

If you later want stricter rollout control, you can explicitly load a specific parameter version in code.

### Override Order

The effective order today is:

1. values from `.env`
2. values loaded from Parameter Manager

So Parameter Manager wins if both define the same key.

### DLP-Specific Loading

If you only want DLP keys from a JSON payload, [`secret_manager.py`](/home/jayant/ulta/ulta-code/adk_web_api/secret_manager.py) already provides:

```python
load_dlp_config_from_secret(secret_id="dlp-config")
```

That helper only exports keys beginning with `DLP_`.

## Troubleshooting

### Import error for Parameter Manager

If startup fails with an import error, install the correct package:

```bash
pip install google-cloud-parametermanager
```

### Parameter loading never happens

Check these first:

1. the startup block in [`main.py`](/home/jayant/ulta/ulta-code/adk_web_api/main.py) is uncommented
2. `LOAD_FROM_PARAMETER_MANAGER=true` is set
3. `GOOGLE_CLOUD_PROJECT` is set
4. `PARAMETER_TO_LOAD` or `PARAMETERS_TO_LOAD` contains the parameter name

### DLP values are not reflected

Make sure:

1. the parameter payload is valid JSON
2. the JSON keys exactly match the environment variable names expected by [`dlp_config.py`](/home/jayant/ulta/ulta-code/adk_web_api/dlp_config.py)
3. parameter loading runs before `create_dlp_plugin(profile="hybrid")`

### JSON parsing error

`set_env_from_secret()` expects the parameter payload to be valid JSON when you load a config parameter like `dlp-config`.

### Permissions issue

If the app can authenticate but cannot read parameters, verify the runtime identity has Parameter Manager read access to the target parameter/version resources.

## Suggested Cleanup Later

The code works conceptually, but these naming updates would make it easier to maintain:

- rename `secret_manager.py` to something like `parameter_manager.py`
- rename `SecretManagerLoader` to `ParameterManagerLoader`
- remove the old compatibility env vars once all deployments use the new names

These are not required for functionality, but they would reduce confusion.

## References

For current Google Cloud Parameter Manager commands and IAM details, see:

- Google Cloud CLI: https://docs.cloud.google.com/sdk/gcloud/reference/parametermanager/parameters/versions
- Parameter Manager version details: https://docs.cloud.google.com/secret-manager/parameter-manager/docs/view-parameter-version-details
- Parameter Manager IAM: https://docs.cloud.google.com/secret-manager/parameter-manager/docs/access-control
