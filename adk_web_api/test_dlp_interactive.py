#!/usr/bin/env python3
"""Interactive DLP testing script.

Run this script to test DLP functionality with different actions and info types.

Usage:
    cd /home/jayant/ulta/ulta-code/adk_web_api
    source ../venv/bin/activate
    python test_dlp_interactive.py
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adk_web_api.dlp_service import DLPService
from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction, InfoTypeConfig, DLPProfiles


def print_separator(title=""):
    """Print a separator line with optional title."""
    if title:
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")
    else:
        print(f"\n{'-' * 60}")


def test_mask_action():
    """Test MASK action - replace with mask characters."""
    print_separator("Testing MASK Action")
    
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
    
    test_texts = [
        "Email: john@example.com",
        "Phone: (555) 123-4567",
        "SSN: 123-45-6789",
        "Card: 4111 1111 1111 1111",
        "IP: 192.168.1.1",
    ]
    
    for text in test_texts:
        result = service.scan(text)
        print(f"\nOriginal: {text}")
        print(f"Masked:   {result.processed_text}")
        print(f"Findings: {len(result.findings)} - {[f.info_type for f in result.findings]}")


def test_redact_action():
    """Test REDACT action - complete removal."""
    print_separator("Testing REDACT Action")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REDACT,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
    )
    service = DLPService(settings)
    
    text = "Contact john@example.com or call (555) 123-4567"
    result = service.scan(text)
    
    print(f"\nOriginal: {text}")
    print(f"Redacted: {result.processed_text}")
    print(f"Removed:  {len(result.findings)} sensitive items")


def test_hash_action():
    """Test HASH action - replace with secure hash."""
    print_separator("Testing HASH Action")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.HASH,
        info_types=["US_SOCIAL_SECURITY_NUMBER", "EMAIL_ADDRESS"]
    )
    service = DLPService(settings)
    
    texts = [
        "SSN: 123-45-6789",
        "Email: sensitive@company.com",
    ]
    
    for text in texts:
        result = service.scan(text)
        print(f"\nOriginal: {text}")
        print(f"Hashed:   {result.processed_text}")
        print(f"Note: Same input will always produce same hash")


def test_replace_action():
    """Test REPLACE action - custom string replacement."""
    print_separator("Testing REPLACE Action")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REPLACE,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
    )
    
    # Configure custom replacements
    settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
        name="EMAIL_ADDRESS",
        custom_replacement="[EMAIL REMOVED]"
    )
    settings.info_type_configs["PHONE_NUMBER"] = InfoTypeConfig(
        name="PHONE_NUMBER",
        custom_replacement="[PHONE REMOVED]"
    )
    
    service = DLPService(settings)
    
    text = "Contact john@example.com or (555) 123-4567"
    result = service.scan(text)
    
    print(f"\nOriginal: {text}")
    print(f"Replaced: {result.processed_text}")


def test_alert_action():
    """Test ALERT action - detect but don't modify."""
    print_separator("Testing ALERT Action (No Modification)")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.ALERT,
        info_types=["EMAIL_ADDRESS", "CREDIT_CARD_NUMBER", "US_SOCIAL_SECURITY_NUMBER"]
    )
    service = DLPService(settings)
    
    text = "Contact john@example.com with card 4111 1111 1111 1111"
    result = service.scan(text)
    
    print(f"\nOriginal:     {text}")
    print(f"Unchanged:    {result.processed_text}")
    print(f"Detected:     {len(result.findings)} sensitive items")
    print(f"Info types:   {[f.info_type for f in result.findings]}")
    print(f"\nNote: Text is unchanged, but detections are logged for audit")


def test_multiple_info_types():
    """Test detection of multiple info types in one text."""
    print_separator("Testing Multiple Info Types")
    
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
    
    text = """
    Contact Information:
    --------------------
    Name: John Doe
    Email: john.doe@example.com
    Phone: (555) 123-4567
    SSN: 123-45-6789
    Card: 4111 1111 1111 1111
    IP: 192.168.1.1
    """
    
    result = service.scan(text)
    
    print(f"\nOriginal Text:{text}")
    print(f"\nMasked Text:{result.processed_text}")
    print(f"\nTotal Findings: {len(result.findings)}")
    
    # Group findings by type
    from collections import Counter
    info_type_counts = Counter(f.info_type for f in result.findings)
    print("\nFindings by Type:")
    for info_type, count in info_type_counts.items():
        print(f"  - {info_type}: {count}")


def test_tool_call_scanning():
    """Test tool call argument scanning."""
    print_separator("Testing Tool Call Scanning")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER"],
        scan_tool_calls=True
    )
    service = DLPService(settings)
    
    # Simulate a tool call
    tool_name = "search_users"
    tool_args = {
        "query": "Find user with email john@example.com",
        "phone_filter": "(555) 123-4567",
        "ssn_lookup": "123-45-6789",
        "limit": 100,  # Non-string, should be preserved
        "active": True  # Non-string, should be preserved
    }
    
    print(f"\nTool: {tool_name}")
    print("\nOriginal Arguments:")
    for key, value in tool_args.items():
        print(f"  {key}: {value}")
    
    masked_args, findings = service.scan_tool_call(tool_name, tool_args)
    
    print("\nMasked Arguments:")
    for key, value in masked_args.items():
        print(f"  {key}: {value}")
    
    print(f"\nFindings: {len(findings)}")
    for finding in findings:
        print(f"  - {finding.info_type}")


def test_disabled_info_types():
    """Test disabling specific info types."""
    print_separator("Testing Disabled Info Types")
    
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.MASK,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
    )
    
    # Disable email detection
    settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
        name="EMAIL_ADDRESS",
        enabled=False
    )
    
    service = DLPService(settings)
    
    text = "Email: john@example.com and Phone: (555) 123-4567"
    result = service.scan(text)
    
    print(f"\nOriginal: {text}")
    print(f"Result:   {result.processed_text}")
    print(f"\nEmail detection disabled, phone detection enabled:")
    print(f"  - Email is NOT masked")
    print(f"  - Phone IS masked")


def test_profiles():
    """Test predefined DLP profiles."""
    print_separator("Testing Predefined Profiles")
    
    profiles = [
        ("basic", DLPProfiles.basic),
        ("standard", DLPProfiles.standard),
        ("enterprise", DLPProfiles.enterprise),
        ("hybrid", DLPProfiles.hybrid),
    ]
    
    for profile_name, profile_func in profiles:
        settings = profile_func()
        print(f"\n{profile_name.upper()} Profile:")
        print(f"  Provider:   {settings.provider.value}")
        print(f"  Action:     {settings.action.value}")
        print(f"  Info Types: {len(settings.info_types)}")
        print(f"  Examples:   {', '.join(settings.info_types[:3])}...")


def test_edge_cases():
    """Test edge cases and special scenarios."""
    print_separator("Testing Edge Cases")
    
    settings = DLPSettings(provider=DLPProvider.REGEX, action=DLPAction.MASK)
    service = DLPService(settings)
    
    edge_cases = [
        ("Empty text", ""),
        ("No PII", "This is just regular text without any sensitive data"),
        ("Multiple emails", "Contact a@x.com, b@y.com, c@z.com for help"),
        ("Email in URL", "Visit https://user@example.com/page"),
        ("SSN-like number", "Part number: 123-45-678 (not an SSN)"),
    ]
    
    for name, text in edge_cases:
        result = service.scan(text)
        print(f"\n{name}:")
        print(f"  Input:   {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"  Output:  {result.processed_text[:50]}{'...' if len(result.processed_text) > 50 else ''}")
        print(f"  Changed: {result.was_modified}")


def run_all_tests():
    """Run all test functions."""
    print("\n" + "=" * 60)
    print("  DLP PLUGIN - COMPREHENSIVE TEST SUITE")
    print("=" * 60)
    
    test_mask_action()
    test_redact_action()
    test_hash_action()
    test_replace_action()
    test_alert_action()
    test_multiple_info_types()
    test_tool_call_scanning()
    test_disabled_info_types()
    test_profiles()
    test_edge_cases()
    
    print("\n" + "=" * 60)
    print("  ALL TESTS COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print()


def run_quick_test():
    """Run a quick test of basic functionality."""
    print("\n" + "=" * 60)
    print("  DLP PLUGIN - QUICK TEST")
    print("=" * 60)
    
    # Quick test with basic settings
    service = DLPService(DLPProfiles.basic())
    
    text = "Contact john@example.com at (555) 123-4567, SSN: 123-45-6789"
    result = service.scan(text)
    
    print(f"\nOriginal: {text}")
    print(f"Masked:   {result.processed_text}")
    print(f"Findings: {len(result.findings)}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="DLP Plugin Test Suite")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick test only"
    )
    parser.add_argument(
        "--action",
        choices=["mask", "redact", "hash", "replace", "alert"],
        help="Test specific action"
    )
    
    args = parser.parse_args()
    
    if args.quick:
        run_quick_test()
    elif args.action:
        # Run specific action test
        action_tests = {
            "mask": test_mask_action,
            "redact": test_redact_action,
            "hash": test_hash_action,
            "replace": test_replace_action,
            "alert": test_alert_action,
        }
        action_tests[args.action]()
    else:
        run_all_tests()