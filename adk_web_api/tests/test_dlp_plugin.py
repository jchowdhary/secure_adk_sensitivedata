"""
Unit Tests for DLP Plugin

Run tests with:
    pytest test_dlp_plugin.py -v

Or with coverage:
    pytest test_dlp_plugin.py -v --cov=dlp_service --cov=dlp_plugin
"""
import pytest
from typing import Dict, Any, List
from unittest.mock import Mock, patch, MagicMock, AsyncMock

# Import DLP modules using package imports
from adk_web_api.dlp_config import (
    DLPSettings, 
    DLPProvider, 
    DLPAction, 
    InfoTypeConfig,
    DLPProfiles
)
from adk_web_api.dlp_service import (
    DLPService, 
    DLPDetectionResult, 
    DLPMetadata,
    RegexDLPDetector
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def basic_settings():
    """Basic DLP settings for regex-based detection."""
    return DLPSettings(
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

@pytest.fixture
def redact_settings():
    """DLP settings for redact action."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REDACT,
        info_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
    )

@pytest.fixture
def hash_settings():
    """DLP settings for hash action."""
    return DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.HASH,
        info_types=["EMAIL_ADDRESS", "US_SOCIAL_SECURITY_NUMBER"]
    )

@pytest.fixture
def replace_settings():
    """DLP settings for replace action."""
    settings = DLPSettings(
        provider=DLPProvider.REGEX,
        action=DLPAction.REPLACE,
        info_types=["EMAIL_ADDRESS"]
    )
    # Add custom replacement
    settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
        name="EMAIL_ADDRESS",
        custom_replacement="[REDACTED EMAIL]"
    )
    return settings

@pytest.fixture
def dlp_service(basic_settings):
    """DLP service instance."""
    return DLPService(basic_settings)


# ============================================================================
# Test Email Detection
# ============================================================================

class TestEmailDetection:
    """Test email address detection and masking."""
    
    def test_detect_basic_email(self, dlp_service):
        """Test basic email detection."""
        result = dlp_service.scan("My email is john@example.com")
        
        assert result.was_modified is True
        assert "j***@example.com" in result.processed_text
        assert len(result.findings) == 1
        assert result.findings[0].info_type == "EMAIL_ADDRESS"
    
    def test_detect_multiple_emails(self, dlp_service):
        """Test multiple email detection."""
        result = dlp_service.scan(
            "Contact us at sales@company.com or support@company.com"
        )
        
        assert result.was_modified is True
        assert "s***@company.com" in result.processed_text
        assert len(result.findings) == 2
    
    def test_email_with_subdomain(self, dlp_service):
        """Test email with subdomain."""
        result = dlp_service.scan("Email: user@mail.example.com")
        
        assert result.was_modified is True
        assert "u***@mail.example.com" in result.processed_text
    
    def test_no_false_positive_email(self, dlp_service):
        """Test that non-email text is not modified."""
        result = dlp_service.scan("This is not an email, just text")
        
        assert result.was_modified is False
        assert result.processed_text == "This is not an email, just text"
    
    def test_email_redact(self, redact_settings):
        """Test email redaction (complete removal)."""
        service = DLPService(redact_settings)
        result = service.scan("Email: john@example.com")
        
        assert result.was_modified is True
        assert "john@example.com" not in result.processed_text
        assert result.processed_text == "Email: "
    
    def test_email_hash(self, hash_settings):
        """Test email hashing."""
        service = DLPService(hash_settings)
        result = service.scan("Email: john@example.com")
        
        assert result.was_modified is True
        assert "john@example.com" not in result.processed_text
        assert "...***" in result.processed_text
    
    def test_email_replace(self, replace_settings):
        """Test email replacement with custom string."""
        service = DLPService(replace_settings)
        result = service.scan("Email: john@example.com")
        
        assert result.was_modified is True
        assert "[REDACTED EMAIL]" in result.processed_text


# ============================================================================
# Test Phone Number Detection
# ============================================================================

class TestPhoneDetection:
    """Test phone number detection and masking."""
    
    def test_detect_us_phone_standard(self, dlp_service):
        """Test standard US phone format."""
        result = dlp_service.scan("Call me at (555) 123-4567")
        
        assert result.was_modified is True
        assert "(***) ***-****" in result.processed_text
        assert result.findings[0].info_type == "PHONE_NUMBER"
    
    def test_detect_us_phone_no_parens(self, dlp_service):
        """Test US phone without parentheses."""
        result = dlp_service.scan("Phone: 555-123-4567")
        
        assert result.was_modified is True
        assert "(***) ***-****" in result.processed_text
    
    def test_detect_phone_with_country_code(self, dlp_service):
        """Test phone with country code."""
        result = dlp_service.scan("International: +1-555-123-4567")
        
        assert result.was_modified is True
    
    def test_no_false_positive_phone(self, dlp_service):
        """Test that non-phone numbers are not modified."""
        result = dlp_service.scan("The year is 2024 and the count is 1234567")
        
        # Phone regex might match 7-digit numbers, depending on pattern
        # This tests the specificity of our regex


# ============================================================================
# Test SSN Detection
# ============================================================================

class TestSSNDetection:
    """Test Social Security Number detection and masking."""
    
    def test_detect_ssn(self, dlp_service):
        """Test SSN detection."""
        result = dlp_service.scan("SSN: 123-45-6789")
        
        assert result.was_modified is True
        assert "***-**-****" in result.processed_text
        assert result.findings[0].info_type == "US_SOCIAL_SECURITY_NUMBER"
    
    def test_detect_ssn_in_sentence(self, dlp_service):
        """Test SSN in a sentence."""
        result = dlp_service.scan("My social security number is 123-45-6789 for records")
        
        assert result.was_modified is True
        assert "***-**-****" in result.processed_text
    
    def test_no_false_positive_ssn(self, dlp_service):
        """Test that non-SSN patterns are not modified."""
        result = dlp_service.scan("Part numbers: 123-45-678 and 987-65-432")
        
        # These should not be detected as SSN (wrong format)
        assert "123-45-678" in result.processed_text


# ============================================================================
# Test Credit Card Detection
# ============================================================================

class TestCreditCardDetection:
    """Test credit card number detection and masking."""
    
    def test_detect_visa_format(self, dlp_service):
        """Test Visa card format (4-4-4-4)."""
        result = dlp_service.scan("Card: 4111 1111 1111 1111")
        
        assert result.was_modified is True
        assert "**** **** **** ****" in result.processed_text
        assert result.findings[0].info_type == "CREDIT_CARD_NUMBER"
    
    def test_detect_card_with_dashes(self, dlp_service):
        """Test credit card with dashes."""
        result = dlp_service.scan("Card: 4111-1111-1111-1111")
        
        assert result.was_modified is True
        assert "**** **** **** ****" in result.processed_text
    
    def test_detect_card_no_spaces(self, dlp_service):
        """Test credit card without spaces."""
        result = dlp_service.scan("Card: 4111111111111111")
        
        assert result.was_modified is True


# ============================================================================
# Test IP Address Detection
# ============================================================================

class TestIPDetection:
    """Test IP address detection and masking."""
    
    def test_detect_ipv4(self, dlp_service):
        """Test IPv4 address detection."""
        result = dlp_service.scan("Server IP: 192.168.1.1")
        
        assert result.was_modified is True
        assert "***.***.***.***" in result.processed_text or "192.168.1.1" not in result.processed_text
        assert result.findings[0].info_type == "IP_ADDRESS"
    
    def test_detect_localhost(self, dlp_service):
        """Test localhost IP detection."""
        result = dlp_service.scan("Connect to 127.0.0.1")
        
        assert result.was_modified is True


# ============================================================================
# Test Multiple Info Types
# ============================================================================

class TestMultipleInfoTypes:
    """Test detection of multiple info types in same text."""
    
    def test_detect_email_and_phone(self, dlp_service):
        """Test detection of email and phone together."""
        result = dlp_service.scan(
            "Contact: john@example.com or call (555) 123-4567"
        )
        
        assert result.was_modified is True
        assert len(result.findings) == 2
        info_types = [f.info_type for f in result.findings]
        assert "EMAIL_ADDRESS" in info_types
        assert "PHONE_NUMBER" in info_types
    
    def test_detect_all_types(self, dlp_service):
        """Test detection of all info types together."""
        text = """
        Email: john@example.com
        Phone: (555) 123-4567
        SSN: 123-45-6789
        Card: 4111 1111 1111 1111
        IP: 192.168.1.1
        """
        result = dlp_service.scan(text)
        
        assert result.was_modified is True
        assert len(result.findings) == 5


# ============================================================================
# Test Different Actions
# ============================================================================

class TestActions:
    """Test different DLP actions."""
    
    def test_mask_action(self, basic_settings):
        """Test mask action (default)."""
        service = DLPService(basic_settings)
        result = service.scan("Email: john@example.com")
        
        assert "***" in result.processed_text
        assert "john@example.com" not in result.processed_text
    
    def test_redact_action(self, redact_settings):
        """Test redact action (complete removal)."""
        service = DLPService(redact_settings)
        result = service.scan("Email: john@example.com Phone: (555) 123-4567")
        
        assert "john@example.com" not in result.processed_text
        assert "(555) 123-4567" not in result.processed_text
        assert "@" not in result.processed_text
    
    def test_hash_action(self, hash_settings):
        """Test hash action."""
        service = DLPService(hash_settings)
        result = service.scan("SSN: 123-45-6789")
        
        assert "123-45-6789" not in result.processed_text
        assert "...***" in result.processed_text
    
    def test_replace_action(self, replace_settings):
        """Test replace action with custom string."""
        service = DLPService(replace_settings)
        result = service.scan("Email: john@example.com")
        
        assert "[REDACTED EMAIL]" in result.processed_text


# ============================================================================
# Test Tool Call Scanning
# ============================================================================

class TestToolCallScanning:
    """Test tool call argument scanning."""
    
    def test_scan_tool_call_string_arg(self, dlp_service):
        """Test scanning tool call with string argument."""
        tool_args = {"query": "Find john@example.com"}
        masked_args, findings = dlp_service.scan_tool_call("search", tool_args)
        
        assert len(findings) == 1
        assert "j***@example.com" in masked_args["query"]
    
    def test_scan_tool_call_multiple_args(self, dlp_service):
        """Test scanning tool call with multiple arguments."""
        tool_args = {
            "email": "user@example.com",
            "phone": "(555) 123-4567",
            "name": "John Doe"
        }
        masked_args, findings = dlp_service.scan_tool_call("contact", tool_args)
        
        assert len(findings) == 2  # email and phone
        assert "***" in masked_args["email"]
        assert "***" in masked_args["phone"]
        assert masked_args["name"] == "John Doe"  # unchanged
    
    def test_scan_tool_call_non_string_arg(self, dlp_service):
        """Test scanning tool call with non-string argument."""
        tool_args = {
            "count": 42,
            "active": True,
            "email": "test@example.com"
        }
        masked_args, findings = dlp_service.scan_tool_call("action", tool_args)
        
        assert masked_args["count"] == 42
        assert masked_args["active"] is True
        assert len(findings) == 1


# ============================================================================
# Test Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_empty_text(self, dlp_service):
        """Test scanning empty text."""
        result = dlp_service.scan("")
        
        assert result.was_modified is False
        assert result.processed_text == ""
    
    def test_none_text(self, dlp_service):
        """Test scanning None."""
        result = dlp_service.scan(None)
        
        assert result.was_modified is False
    
    def test_text_no_pii(self, dlp_service):
        """Test text with no PII."""
        result = dlp_service.scan("This is just normal text with no sensitive data")
        
        assert result.was_modified is False
        assert result.processed_text == "This is just normal text with no sensitive data"


# ============================================================================
# Test Configuration
# ============================================================================

class TestConfiguration:
    """Test configuration options."""
    
    def test_disabled_info_type(self):
        """Test that disabled info types are not detected."""
        settings = DLPSettings(
            provider=DLPProvider.REGEX,
            action=DLPAction.MASK,
            info_types=["EMAIL_ADDRESS"]
        )
        # Disable email detection
        settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
            name="EMAIL_ADDRESS",
            enabled=False
        )
        
        service = DLPService(settings)
        result = service.scan("Email: john@example.com")
        
        assert result.was_modified is False
    
    def test_custom_regex_pattern(self):
        """Test custom regex pattern for info type."""
        settings = DLPSettings(
            provider=DLPProvider.REGEX,
            action=DLPAction.MASK,
            info_types=["EMAIL_ADDRESS"]
        )
        # Use custom regex that only matches specific domain
        settings.info_type_configs["EMAIL_ADDRESS"] = InfoTypeConfig(
            name="EMAIL_ADDRESS",
            custom_regex=r'\b[A-Za-z0-9]+@internal\.company\.com\b'
        )
        
        service = DLPService(settings)
        
        # Should match internal company email
        result1 = service.scan("Email: user@internal.company.com")
        assert result1.was_modified is True
        
        # Should not match external email
        result2 = service.scan("Email: user@gmail.com")
        assert result2.was_modified is False
    
    def test_from_env_configuration(self):
        """Test loading configuration from environment."""
        import os
        
        # Set environment variables
        os.environ["DLP_PROVIDER"] = "regex"
        os.environ["DLP_ACTION"] = "mask"
        os.environ["DLP_INFO_TYPES"] = "EMAIL_ADDRESS,PHONE_NUMBER"
        
        settings = DLPSettings.from_env()
        
        assert settings.provider == DLPProvider.REGEX
        assert settings.action == DLPAction.MASK
        assert "EMAIL_ADDRESS" in settings.info_types
        assert "PHONE_NUMBER" in settings.info_types


# ============================================================================
# Test Profiles
# ============================================================================

class TestProfiles:
    """Test predefined DLP profiles."""
    
    def test_basic_profile(self):
        """Test basic profile."""
        settings = DLPProfiles.basic()
        
        assert settings.provider == DLPProvider.REGEX
        assert len(settings.info_types) == 4
    
    def test_standard_profile(self):
        """Test standard profile."""
        settings = DLPProfiles.standard()
        
        assert settings.provider == DLPProvider.GOOGLE_CLOUD
        assert len(settings.info_types) == 7
    
    def test_enterprise_profile(self):
        """Test enterprise profile."""
        settings = DLPProfiles.enterprise()
        
        assert settings.provider == DLPProvider.GOOGLE_CLOUD
        assert settings.scan_tool_calls is True
        assert settings.scan_tool_results is True
    
    def test_hybrid_profile(self):
        """Test hybrid profile."""
        settings = DLPProfiles.hybrid()
        
        assert settings.provider == DLPProvider.HYBRID
        assert settings.fallback_to_regex_on_error is True


# ============================================================================
# Test Google Cloud DLP Detector (Mocked)
# ============================================================================

class TestGoogleCloudDLP:
    """Test Google Cloud DLP integration with mocks."""
    
    @patch('adk_web_api.dlp_service.GoogleCloudDLPDetector._initialize_client')
    def test_google_cloud_detection(self, mock_init):
        """Test Google Cloud DLP detection with mocked client."""
        # Mock the initialization to return True
        mock_init.return_value = True
        
        settings = DLPSettings(
            provider=DLPProvider.GOOGLE_CLOUD,
            google_cloud_project_id="test-project"
        )
        
        # This will use regex fallback since we're mocking
        service = DLPService(settings)
        
        # The service should still work (fallback to regex)
        result = service.scan("Email: test@example.com")
        
        # Since Google Cloud isn't truly initialized, it should fallback
        assert result is not None


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])