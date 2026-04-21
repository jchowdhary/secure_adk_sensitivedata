# Data Loss Prevention (DLP) Integration

## Overview

This DLP module provides comprehensive data loss prevention capabilities integrated with Google ADK. It offers multiple detection providers, configurable info types, and enterprise-grade protection.

## Why DLP?

### Current Regex vs DLP

| Feature | Regex-based (Current) | Google Cloud DLP |
|---------|----------------------|------------------|
| **Detection Accuracy** | ~60-70% | ~95%+ |
| **Info Types** | 6 basic types | 100+ built-in types |
| **Context Awareness** | ❌ No | ✅ Yes |
| **International Formats** | ❌ Limited | ✅ Global formats |
| **Custom Rules** | ❌ Manual regex | ✅ Custom detectors |
| **Compliance** | ❌ Basic | ✅ HIPAA, PCI, GDPR |
| **Performance** | ✅ Fast (local) | ⚠️ Network latency |

### When to Use DLP

1. **Regulatory Compliance** - HIPAA, PCI-DSS, GDPR, CCPA
2. **Enterprise Security** - Prevent data exfiltration
3. **Multi-format Support** - International phone numbers, addresses
4. **Context-aware Detection** - Distinguish between similar patterns
5. **Audit Requirements** - Enterprise-grade logging and reporting

## Installation

### Required Python Modules

```bash
# For regex-based DLP (already available)
# No additional packages needed

# For Google Cloud DLP (enterprise)
pip install google-cloud-dlp

# Optional: For enhanced logging
pip install google-cloud-logging
```

### Environment Variables

Create or update `.env` file:

```env
# DLP Configuration
DLP_PROVIDER=regex  # Options: regex, google_cloud, hybrid
DLP_ACTION=mask     # Options: mask, redact, replace, hash, alert
DLP_MASK_CHAR=*
DLP_MIN_LIKELIHOOD_THRESHOLD=LIKELY  # VERY_LIKELY, LIKELY, POSSIBLE, UNLIKELY

# Info types to detect (pipe-separated)
DLP_INFO_TYPES=EMAIL_ADDRESS|PHONE_NUMBER|US_SOCIAL_SECURITY_NUMBER|CREDIT_CARD_NUMBER

# Scopes (what to scan)
DLP_SCAN_USER_MESSAGES=true
DLP_SCAN_LLM_REQUESTS=true
DLP_SCAN_LLM_RESPONSES=true
DLP_SCAN_TOOL_CALLS=true
DLP_SCAN_TOOL_RESULTS=true

# Agent Filtering (which agents to scan)
DLP_AGENT_FILTER_MODE=all          # Options: all, allowlist, blocklist
DLP_ENABLED_AGENTS=orchestrator|sub_agent      # For allowlist mode (pipe-separated)
DLP_DISABLED_AGENTS=public-agent|external-agent  # For blocklist mode (pipe-separated)

# Google Cloud DLP (required for google_cloud provider)
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Error handling
DLP_FALLBACK_TO_REGEX=true
DLP_SKIP_ON_ERROR=false

# Email domain bypass
DLP_ENABLE_EMAIL_DOMAIN_BYPASS=true
DLP_BYPASS_EMAIL_DOMAINS=ulta.com|example.com
DLP_BYPASS_EMAIL_SUBDOMAINS=true
```

### Email Domain Bypass

These settings allow trusted company or internal email domains to bypass masking.

```env
DLP_ENABLE_EMAIL_DOMAIN_BYPASS=true
DLP_BYPASS_EMAIL_DOMAINS=ulta.com|example.com
DLP_BYPASS_EMAIL_SUBDOMAINS=true
```

Behavior:

- `DLP_ENABLE_EMAIL_DOMAIN_BYPASS=true` enables the bypass logic
- `DLP_BYPASS_EMAIL_DOMAINS` is a pipe-separated allowlist of domains
- `DLP_BYPASS_EMAIL_SUBDOMAINS=true` also bypasses subdomains like `team.ulta.com`

Examples:

- `user@ulta.com` is bypassed when `ulta.com` is listed
- `user@team.ulta.com` is also bypassed when subdomain bypass is enabled
- `user@gmail.com` is still scanned unless `gmail.com` is explicitly listed

## Usage

### Quick Start (Regex-based)

```python
from adk_web_api.dlp_plugin import create_dlp_plugin

# Create DLP plugin with basic profile
dlp_plugin = create_dlp_plugin(profile="basic")

# Use with ADK Runner
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService

runner = Runner(
    app_name="MyApp",
    agent=my_agent,
    session_service=InMemorySessionService(),
    plugins=[dlp_plugin]
)
```

### Using Predefined Profiles

```python
from adk_web_api.dlp_plugin import create_dlp_plugin

# Basic - Regex-based, minimal info types
dlp_plugin = create_dlp_plugin(profile="basic")

# Standard - Google Cloud DLP, common info types
dlp_plugin = create_dlp_plugin(profile="standard")

# Enterprise - Google Cloud DLP, comprehensive info types
dlp_plugin = create_dlp_plugin(profile="enterprise")

# Hybrid - Both providers, best coverage
dlp_plugin = create_dlp_plugin(profile="hybrid")
```

### Custom Configuration

```python
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction
from adk_web_api.dlp_plugin import DLPPlugin

# Create custom settings
settings = DLPSettings(
    provider=DLPProvider.GOOGLE_CLOUD,
    action=DLPAction.MASK,
    google_cloud_project_id="my-project-id",
    
    # Only scan specific info types
    info_types=[
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SOCIAL_SECURITY_NUMBER",
        "CREDIT_CARD_NUMBER",
        "PERSON_NAME",
    ],
    
    # Control what to scan
    scan_user_messages=True,
    scan_llm_requests=True,
    scan_llm_responses=True,
    scan_tool_calls=True,
    scan_tool_results=True,
    
    # Error handling
    fallback_to_regex_on_error=True,
)

# Create plugin
dlp_plugin = DLPPlugin(settings=settings)
```

### Combining with Existing PII Masking Plugin

You can use both plugins together for layered protection:

```python
from adk_web_api.pii_masking_plugin import create_pii_masking_plugin
from adk_web_api.dlp_plugin import create_dlp_plugin

# Both plugins will run in order
runner = Runner(
    app_name="MyApp",
    agent=my_agent,
    session_service=InMemorySessionService(),
    plugins=[
        create_pii_masking_plugin(),  # Fast, local regex
        create_dlp_plugin(profile="standard"),  # More accurate Google Cloud DLP
    ]
)
```

## Supported Info Types

### Built-in Info Types (Regex)

- `EMAIL_ADDRESS` - Email addresses
- `PHONE_NUMBER` - US phone numbers
- `US_SOCIAL_SECURITY_NUMBER` - SSN
- `CREDIT_CARD_NUMBER` - Credit card numbers
- `IP_ADDRESS` - IPv4 addresses
- `API_KEY` - API keys (pattern-based)
- `AUTH_TOKEN` - Authentication tokens
- `DATE_OF_BIRTH` - DOB fields
- `PASSPORT_NUMBER` - Generic passport numbers
- `US_DRIVER_LICENSE_NUMBER` - Driver's license numbers

### Google Cloud DLP Info Types (100+)

Including:
- `PERSON_NAME` - Names
- `LOCATION` - Addresses, cities, countries
- `ORGANIZATION_NAME` - Company names
- `DATE` - Dates in various formats
- `AGE` - Age information
- `MEDICAL_TERM` - Medical terminology
- `US_BANK_ACCOUNT_NUMBER` - Bank accounts
- `IBAN_CODE` - International bank accounts
- `HTTP_HEADERS` - Sensitive HTTP headers
- And many more...

See [Google Cloud DLP Info Types](https://cloud.google.com/dlp/docs/infotypes-reference) for complete list.

## Actions

| Action | Description | Example |
|--------|-------------|---------|
| `MASK` | Replace with mask characters | `john@example.com` → `j***@example.com` |
| `REDACT` | Remove completely | `john@example.com` → `` |
| `REPLACE` | Replace with custom string | `john@example.com` → `[REDACTED]` |
| `HASH` | Replace with secure hash | `john@example.com` → `a1b2c3d4...***` |
| `ALERT` | Alert only, don't modify | Logged but not changed |

## Agent Filtering

Control which agents have DLP protection applied:

### Agent Filter Modes

| Mode | DLP_ENABLED_AGENTS | DLP_DISABLED_AGENTS | Behavior |
|------|-------------------|--------------------|----------|
| `all` | Ignored | Ignored | DLP applies to **ALL agents** (default) |
| `allowlist` | **Used** | Ignored | DLP applies **only** to agents in enabled list |
| `blocklist` | Ignored | **Used** | DLP applies to all agents **except** those in disabled list |

### Usage Examples

**Allowlist Mode (Whitelist - More Secure):**
```env
DLP_AGENT_FILTER_MODE=allowlist
DLP_ENABLED_AGENTS=orchestrator|sub_agent
```
Only `orchestrator` and `sub_agent` will have DLP scanning.

**Blocklist Mode (Blacklist - More Permissive):**
```env
DLP_AGENT_FILTER_MODE=blocklist
DLP_DISABLED_AGENTS=public-agent|external-agent
```
All agents get DLP scanning **except** `public-agent` and `external-agent`.

**All Mode (Default):**
```env
DLP_AGENT_FILTER_MODE=all
```
All agents get DLP scanning regardless of list values.

### Programmatic Configuration

```python
from adk_web_api.dlp_config import DLPSettings, AgentFilterMode

# Allowlist - only scan specific agents
settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    agent_filter_mode=AgentFilterMode.ALLOWLIST,
    enabled_agents=["orchestrator", "sub_agent"],
)

# Blocklist - scan all except specific agents
settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    agent_filter_mode=AgentFilterMode.BLOCKLIST,
    disabled_agents=["public-agent", "external-agent"],
)
```

## Tool Call Protection

The DLP plugin automatically scans tool calls and results:

```python
# Tool calls are scanned before execution
# Example: google_search tool
tool_args = {"query": "My SSN is 123-45-6789"}
# After DLP: {"query": "My SSN is ***-**-****"}

# Tool results are scanned after execution
# Example: API response
result = {"data": "User email: john@example.com"}
# After DLP: {"data": "User email: j***@example.com"}
```

## Error Handling

### Fallback to Regex

If Google Cloud DLP fails, automatically fall back to regex:

```python
settings = DLPSettings(
    provider=DLPProvider.GOOGLE_CLOUD,
    fallback_to_regex_on_error=True,  # Enable fallback
)
```

### Skip on Error

If all detection fails, choose how to handle:

```python
settings = DLPSettings(
    skip_on_error=False,  # Let text through unmasked (fail-open)
    # OR
    skip_on_error=True,   # Replace with [DLP_ERROR] (fail-closed)
)
```

## Audit Logging

All DLP operations are logged with:

- Timestamp
- Info types detected
- Likelihood score
- Original vs. masked values (configurable)
- Context (user message, LLM request, tool call, etc.)

Example log output:

```
📋 AUDIT: DLP Content Processing - user_message
   └─ Timestamp: 2026-04-01T12:34:56.789
   └─ findings_count: 2
   └─ info_types: ['EMAIL_ADDRESS', 'PHONE_NUMBER']
```

## Performance Considerations

| Provider | Latency | Accuracy | Cost |
|----------|---------|----------|------|
| Regex | <1ms | ~60-70% | Free |
| Google Cloud DLP | 100-500ms | ~95%+ | Per-request pricing |
| Hybrid | 100-500ms | ~95%+ | Google Cloud pricing |

### Recommendations

1. **Development** - Use regex (fast, free)
2. **Production** - Use hybrid (accurate, with fallback)
3. **Enterprise** - Use Google Cloud DLP with Cloud Logging

## Migration from PII Masking Plugin

To migrate from the old PII masking plugin to DLP:

```python
# Old (regex-only)
from adk_web_api.pii_masking_plugin import create_pii_masking_plugin
plugin = create_pii_masking_plugin()

# New (DLP with same functionality)
from adk_web_api.dlp_plugin import create_dlp_plugin
plugin = create_dlp_plugin(profile="basic")

# Or upgrade to Google Cloud DLP
plugin = create_dlp_plugin(profile="standard")
```

## Testing Guide

### Running Unit Tests

```bash
# Install pytest if not already installed
pip install pytest pytest-cov

# Run all tests
cd /home/jayant/ulta/ulta-code
source venv/bin/activate
pytest adk_web_api/tests/test_dlp_plugin.py -v

# Run with coverage report
pytest adk_web_api/tests/test_dlp_plugin.py -v --cov=dlp_service --cov=dlp_plugin

# Run specific test class
pytest adk_web_api/tests/test_dlp_plugin.py::TestEmailDetection -v

# Run specific test
pytest adk_web_api/tests/test_dlp_plugin.py::TestEmailDetection::test_detect_basic_email -v
```

### Testing Different Info Types

#### Test 1: Email Address Detection
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

# Setup
settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["EMAIL_ADDRESS"]
)
service = DLPService(settings)

# Test various email formats
emails = [
    "john@example.com",
    "john.doe@example.com",
    "user+tag@example.co.uk",
    "sales@company.com",
]

for email in emails:
    result = service.scan(f"Contact: {email}")
    print(f"Original: {result.original_text}")
    print(f"Masked:   {result.processed_text}")
    print(f"Found:    {len(result.findings)} detection(s)\n")
```

#### Test 2: Phone Number Detection
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["PHONE_NUMBER"]
)
service = DLPService(settings)

# Test various phone formats
phones = [
    "(555) 123-4567",
    "555-123-4567",
    "+1-555-123-4567",
    "5551234567",
]

for phone in phones:
    result = service.scan(f"Phone: {phone}")
    print(f"Original: {result.original_text}")
    print(f"Masked:   {result.processed_text}\n")
```

#### Test 3: SSN Detection
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["US_SOCIAL_SECURITY_NUMBER"]
)
service = DLPService(settings)

# Test SSN
ssns = [
    "123-45-6789",
    "My SSN is 123-45-6789 for verification",
]

for text in ssns:
    result = service.scan(text)
    print(f"Original: {result.original_text}")
    print(f"Masked:   {result.processed_text}\n")
```

#### Test 4: Credit Card Detection
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["CREDIT_CARD_NUMBER"]
)
service = DLPService(settings)

# Test credit card formats
cards = [
    "4111 1111 1111 1111",     # Visa (spaces)
    "4111-1111-1111-1111",     # Visa (dashes)
    "5500 0000 0000 0004",     # Mastercard
]

for card in cards:
    result = service.scan(f"Card: {card}")
    print(f"Original: {result.original_text}")
    print(f"Masked:   {result.processed_text}\n")
```

#### Test 5: IP Address Detection
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["IP_ADDRESS"]
)
service = DLPService(settings)

# Test IP addresses
ips = [
    "192.168.1.1",
    "10.0.0.1",
    "127.0.0.1",
    "8.8.8.8",
]

for ip in ips:
    result = service.scan(f"Server: {ip}")
    print(f"Original: {result.original_text}")
    print(f"Masked:   {result.processed_text}\n")
```

### Testing Different Actions

#### Action 1: MASK (Default)
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,  # Replace with mask characters
    info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
)
service = DLPService(settings)

result = service.scan("Contact: john@example.com, Phone: (555) 123-4567")

print(f"Original: {result.original_text}")
print(f"Masked:   {result.processed_text}")
# Output: Contact: j***@example.com, Phone: (***) ***-****
```

#### Action 2: REDACT (Complete Removal)
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.REDACT,  # Remove completely
    info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
)
service = DLPService(settings)

result = service.scan("Contact: john@example.com, Phone: (555) 123-4567")

print(f"Original: {result.original_text}")
print(f"Redacted: {result.processed_text}")
# Output: Contact: , Phone: 
```

#### Action 3: REPLACE (Custom String)
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction, InfoTypeConfig

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.REPLACE,  # Replace with custom string
    info_types=["EMAIL_ADDRESS"]
)

# Configure custom replacement for each info type
settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
    name="EMAIL_ADDRESS",
    custom_replacement="[EMAIL REMOVED FOR PRIVACY]"
)

service = DLPService(settings)

result = service.scan("Contact: john@example.com for support")

print(f"Original: {result.original_text}")
print(f"Replaced: {result.processed_text}")
# Output: Contact: [EMAIL REMOVED FOR PRIVACY] for support
```

#### Action 4: HASH (Secure Hash)
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.HASH,  # Replace with secure hash
    info_types=["US_SOCIAL_SECURITY_NUMBER"]
)
service = DLPService(settings)

result = service.scan("SSN: 123-45-6789")

print(f"Original: {result.original_text}")
print(f"Hashed:   {result.processed_text}")
# Output: SSN: a1b2c3d4...***
# Note: Same SSN will always produce the same hash
```

#### Action 5: ALERT (Alert Only, Don't Modify)
```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.ALERT,  # Alert but don't modify
    info_types=["EMAIL_ADDRESS", "CREDIT_CARD_NUMBER"],
    log_detailed_findings=True
)
service = DLPService(settings)

result = service.scan("Contact: john@example.com")

print(f"Original:     {result.original_text}")
print(f"Unchanged:    {result.processed_text}")
print(f"Findings:     {len(result.findings)}")
print(f"Info types:   {[f.info_type for f in result.findings]}")
# Output: Text is unchanged, but findings are logged
```

### Testing with Google Cloud DLP

```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

# Requires Google Cloud credentials and DLP API enabled
settings = DLPSettings(
    provider=DLPProvider.GOOGLE_CLOUD,
    action=DLPAction.MASK,
    google_cloud_project_id="prj-dev-05022026",
    info_types=[
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON_NAME",       # Not available in regex!
        "LOCATION",          # Not available in regex!
        "DATE_OF_BIRTH",      # Better accuracy than regex
    ]
)
service = DLPService(settings)

# Google Cloud DLP can detect more info types with context awareness
result = service.scan(
    "Contact John Smith at john@example.com, "
    "located in New York, born on 01/15/1990"
)

print(f"Original: {result.original_text}")
print(f"Masked:   {result.processed_text}")
print(f"Findings: {len(result.findings)}")
for finding in result.findings:
    print(f"  - {finding.info_type}: likelihood={finding.likelihood}")
```

### Testing Tool Call Integration

```python
from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction

settings = DLPSettings(
    provider=DLPProvider.REGEX,
    action=DLPAction.MASK,
    info_types=["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER"],
    scan_tool_calls=True
)
service = DLPService(settings)

# Simulate a tool call with sensitive data
tool_args = {
    "query": "Find user with email john@example.com",
    "filter": "phone = (555) 123-4567",
    "ssn": "123-45-6789",
    "count": 100  # Non-string values are preserved
}

masked_args, findings = service.scan_tool_call("search_users", tool_args)

print("Original arguments:")
for key, value in tool_args.items():
    print(f"  {key}: {value}")

print("\nMasked arguments:")
for key, value in masked_args.items():
    print(f"  {key}: {value}")

print(f"\nTotal findings: {len(findings)}")
for finding in findings:
    print(f"  - {finding.info_type}")
```

### Interactive Testing Script

Create a file `test_dlp_interactive.py`:

```python
#!/usr/bin/env python3
"""Interactive DLP testing script."""
from dlp_service import DLPService
from dlp_config import DLPSettings, DLPProvider, DLPAction

def test_mask():
    print("\n=== Testing MASK Action ===")
    settings = DLPSettings(provider=DLPProvider.REGEX, action=DLPAction.MASK)
    service = DLPService(settings)
    
    test_texts = [
        "Email: john@example.com",
        "Phone: (555) 123-4567",
        "SSN: 123-45-6789",
        "Card: 4111 1111 1111 1111",
        "IP: 192.168.1.1",
    ]
    
    for text in test_texts:
        result = service.scan(text)
        print(f"\nOriginal: {result.original_text}")
        print(f"Masked:   {result.processed_text}")

def test_redact():
    print("\n=== Testing REDACT Action ===")
    settings = DLPSettings(provider=DLPProvider.REGEX, action=DLPAction.REDACT)
    service = DLPService(settings)
    
    result = service.scan("Email: john@example.com and phone (555) 123-4567")
    print(f"\nOriginal: {result.original_text}")
    print(f"Redacted: {result.processed_text}")

def test_hash():
    print("\n=== Testing HASH Action ===")
    settings = DLPSettings(provider=DLPProvider.REGEX, action=DLPAction.HASH)
    service = DLPService(settings)
    
    result = service.scan("SSN: 123-45-6789")
    print(f"\nOriginal: {result.original_text}")
    print(f"Hashed:   {result.processed_text}")

def test_all_types():
    print("\n=== Testing All Info Types ===")
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=[
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_SOCIAL_SECURITY_NUMBER",
            "CREDIT_CARD_NUMBER",
            "IP_ADDRESS",
        ]
    )
    service = DLPService(settings)
    
    text = """Contact Information:
    Email: john.doe@example.com
    Phone: (555) 123-4567
    SSN: 123-45-6789
    Card: 4111 1111 1111 1111
    IP: 192.168.1.1
    """
    
    result = service.scan(text)
    print(f"\nOriginal:\n{result.original_text}")
    print(f"\nMasked:\n{result.processed_text}")
    print(f"\nFindings: {len(result.findings)}")

if __name__ == "__main__":
    print("DLP Interactive Testing")
    print("=" * 50)
    
    test_mask()
    test_redact()
    test_hash()
    test_all_types()
    
    print("\n" + "=" * 50)
    print("Testing complete!")
```

Run it:
```bash
cd /home/jayant/ulta/ulta-code/adk_web_api
source ../venv/bin/activate
python test_dlp_interactive.py
```

## Troubleshooting

### google-cloud-dlp not found

```bash
pip install google-cloud-dlp
```

### Google Cloud authentication failed

1. Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable
2. Ensure service account has `dlp.serviceAgent` role
3. Verify project ID in `GOOGLE_CLOUD_PROJECT`

### High latency

- Use `DLPProvider.REGEX` for faster processing
- Use `DLPProvider.HYBRID` for best balance
- Enable `fallback_to_regex_on_error=True`

### False positives

- Use Google Cloud DLP for context-aware detection
- Set `likelihood_threshold` to `VERY_LIKELY`
- Use custom info type configurations
