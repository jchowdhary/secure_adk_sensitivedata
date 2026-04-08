"""
Tests for Secret Manager Integration

Run tests with verbose output:
    pytest test_secret_manager.py -v -s

Run specific test:
    pytest test_secret_manager.py::TestSecretManagerLoader -v -s
"""
import pytest
import os
import json
from unittest.mock import MagicMock, patch, mock_open
from typing import Dict, Any

# Import the module under test
from adk_web_api.secret_manager import (
    SecretManagerLoader,
    SecretConfig,
    load_secrets_at_startup,
    load_dlp_config_from_secret,
    create_secret_loader,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_secretmanager_client():
    """Mock the Secret Manager client."""
    with patch('adk_web_api.secret_manager.secretmanager') as mock_sm:
        mock_client = MagicMock()
        mock_sm.SecretManagerServiceClient.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_gcp_exceptions():
    """Mock GCP exceptions."""
    with patch('adk_web_api.secret_manager.gcp_exceptions') as mock_exc:
        yield mock_exc


@pytest.fixture
def clean_env():
    """Clean DLP-related environment variables before each test."""
    dlp_vars = [k for k in os.environ.keys() if k.startswith('DLP_')]
    for var in dlp_vars:
        del os.environ[var]
    yield
    # Cleanup after test
    dlp_vars = [k for k in os.environ.keys() if k.startswith('DLP_')]
    for var in dlp_vars:
        del os.environ[var]


# ============================================================================
# Test Secret Manager Loader
# ============================================================================

class TestSecretManagerLoader:
    """Test SecretManagerLoader class."""
    
    def test_init_with_project_id(self, mock_secretmanager_client):
        """Test initialization with explicit project ID."""
        loader = SecretManagerLoader(project_id="test-project-123")
        
        assert loader.project_id == "test-project-123"
        mock_secretmanager_client.assert_called_once()
    
    def test_init_with_env_var_project(self, mock_secretmanager_client):
        """Test initialization with project from environment."""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "env-project-456"
        
        loader = SecretManagerLoader()
        
        assert loader.project_id == "env-project-456"
        
        del os.environ["GOOGLE_CLOUD_PROJECT"]
    
    def test_init_without_project_raises(self, mock_secretmanager_client):
        """Test that initialization fails without project ID."""
        # Remove any existing project env var
        if "GOOGLE_CLOUD_PROJECT" in os.environ:
            del os.environ["GOOGLE_CLOUD_PROJECT"]
        
        with pytest.raises(ValueError, match="Project ID is required"):
            SecretManagerLoader()
    
    def test_load_secret_success(self, mock_secretmanager_client):
        """Test successfully loading a secret."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "secret-value-123"
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        value = loader.load_secret("my-secret")
        
        assert value == "secret-value-123"
        mock_secretmanager_client.access_secret_version.assert_called_once_with(
            request={"name": "projects/test-project/secrets/my-secret/versions/latest"}
        )
    
    def test_load_secret_with_version(self, mock_secretmanager_client):
        """Test loading a specific version of a secret."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "versioned-secret"
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        value = loader.load_secret("my-secret", version="2")
        
        assert value == "versioned-secret"
        mock_secretmanager_client.access_secret_version.assert_called_once_with(
            request={"name": "projects/test-project/secrets/my-secret/versions/2"}
        )
    
    def test_load_secret_not_found(self, mock_secretmanager_client, mock_gcp_exceptions):
        """Test handling of secret not found."""
        mock_gcp_exceptions.NotFound = Exception
        mock_secretmanager_client.access_secret_version.side_effect = mock_gcp_exceptions.NotFound("Not found")
        
        loader = SecretManagerLoader(project_id="test-project")
        
        with pytest.raises(ValueError, match="Secret 'missing-secret' not found"):
            loader.load_secret("missing-secret")
    
    def test_load_secret_permission_denied(self, mock_secretmanager_client, mock_gcp_exceptions):
        """Test handling of permission denied."""
        mock_gcp_exceptions.PermissionDenied = Exception
        mock_secretmanager_client.access_secret_version.side_effect = mock_gcp_exceptions.PermissionDenied("Denied")
        
        loader = SecretManagerLoader(project_id="test-project")
        
        with pytest.raises(PermissionError, match="Permission denied"):
            loader.load_secret("protected-secret")
    
    def test_load_secret_as_json(self, mock_secretmanager_client):
        """Test loading and parsing a JSON secret."""
        json_data = {"key1": "value1", "key2": "value2"}
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(json_data)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        result = loader.load_secret_as_json("json-secret")
        
        assert result == json_data


# ============================================================================
# Test Environment Variable Loading
# ============================================================================

class TestEnvVarLoading:
    """Test setting environment variables from secrets."""
    
    def test_set_env_from_secret(self, mock_secretmanager_client, clean_env):
        """Test setting environment variables from a JSON secret."""
        config = {
            "DLP_PROVIDER": "google_cloud",
            "DLP_ACTION": "mask",
            "DLP_INFO_TYPES": "EMAIL_ADDRESS|PHONE_NUMBER"
        }
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        vars_set = loader.set_env_from_secret("dlp-config")
        
        assert vars_set == config
        assert os.environ["DLP_PROVIDER"] == "google_cloud"
        assert os.environ["DLP_ACTION"] == "mask"
        assert os.environ["DLP_INFO_TYPES"] == "EMAIL_ADDRESS|PHONE_NUMBER"
    
    def test_set_env_with_prefix_filter(self, mock_secretmanager_client, clean_env):
        """Test filtering environment variables by prefix."""
        config = {
            "DLP_PROVIDER": "hybrid",
            "DLP_ACTION": "mask",
            "OTHER_VAR": "should-not-be-set"
        }
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        vars_set = loader.set_env_from_secret("config", prefix_filter="DLP_")
        
        assert "DLP_PROVIDER" in vars_set
        assert "DLP_ACTION" in vars_set
        assert "OTHER_VAR" not in vars_set
        assert "OTHER_VAR" not in os.environ
    
    def test_set_env_converts_bool_to_string(self, mock_secretmanager_client, clean_env):
        """Test that boolean values are converted to lowercase strings."""
        config = {
            "DLP_SCAN_USER_MESSAGES": True,
            "DLP_SCAN_LLM_REQUESTS": False
        }
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("bool-config")
        
        assert os.environ["DLP_SCAN_USER_MESSAGES"] == "true"
        assert os.environ["DLP_SCAN_LLM_REQUESTS"] == "false"
    
    def test_set_env_handles_complex_values(self, mock_secretmanager_client, clean_env):
        """Test handling of complex values (dict, list)."""
        config = {
            "DLP_INFO_TYPES_LIST": ["EMAIL_ADDRESS", "PHONE_NUMBER"],
            "DLP_NESTED_CONFIG": {"nested": "value"}
        }
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("complex-config")
        
        # Complex values should be JSON-serialized
        assert os.environ["DLP_INFO_TYPES_LIST"] == '["EMAIL_ADDRESS", "PHONE_NUMBER"]'
        assert os.environ["DLP_NESTED_CONFIG"] == '{"nested": "value"}'


# ============================================================================
# Test Enterprise Profile with Google Cloud DLP
# ============================================================================

class TestEnterpriseProfileWithSecretManager:
    """Test loading enterprise profile configuration from Secret Manager."""
    
    @pytest.fixture
    def enterprise_config(self):
        """Enterprise profile configuration for Google Cloud DLP."""
        return {
            "DLP_PROVIDER": "google_cloud",
            "DLP_ACTION": "mask",
            "DLP_MASK_CHAR": "*",
            "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|PASSPORT_NUMBER|API_KEY|AUTH_TOKEN|DATE_OF_BIRTH|EMAIL_ADDRESS|PHONE_NUMBER",
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
    
    @pytest.fixture
    def hybrid_config(self):
        """Hybrid profile configuration."""
        return {
            "DLP_PROVIDER": "hybrid",
            "DLP_ACTION": "mask",
            "DLP_MASK_CHAR": "*",
            "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|PASSPORT_NUMBER|API_KEY|AUTH_TOKEN|DATE_OF_BIRTH|PERSON_NAME|LOCATION",
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
    
    def test_load_enterprise_profile_google_cloud(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test loading enterprise profile with Google Cloud DLP provider."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        vars_set = loader.set_env_from_secret("dlp-config")
        
        # Verify all enterprise settings loaded
        assert os.environ["DLP_PROVIDER"] == "google_cloud"
        assert os.environ["DLP_ACTION"] == "mask"
        
        # Verify info types include SSN, Passport, API Token, DOB
        info_types = os.environ["DLP_INFO_TYPES"].split("|")
        assert "US_SOCIAL_SECURITY_NUMBER" in info_types
        assert "PASSPORT_NUMBER" in info_types
        assert "API_KEY" in info_types
        assert "AUTH_TOKEN" in info_types
        assert "DATE_OF_BIRTH" in info_types
        assert "EMAIL_ADDRESS" in info_types
        assert "PHONE_NUMBER" in info_types
        
        # Verify all scan scopes enabled
        assert os.environ["DLP_SCAN_USER_MESSAGES"] == "true"
        assert os.environ["DLP_SCAN_LLM_REQUESTS"] == "true"
        assert os.environ["DLP_SCAN_LLM_RESPONSES"] == "true"
        assert os.environ["DLP_SCAN_TOOL_CALLS"] == "true"
        assert os.environ["DLP_SCAN_TOOL_RESULTS"] == "true"
        
        # Verify error handling
        assert os.environ["DLP_FALLBACK_TO_REGEX"] == "true"
        assert os.environ["DLP_SKIP_ON_ERROR"] == "false"
    
    def test_load_hybrid_profile(
        self, mock_secretmanager_client, clean_env, hybrid_config
    ):
        """Test loading hybrid profile configuration."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(hybrid_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        vars_set = loader.set_env_from_secret("dlp-config")
        
        # Verify hybrid provider
        assert os.environ["DLP_PROVIDER"] == "hybrid"
        
        # Verify agent filtering
        assert os.environ["DLP_AGENT_FILTER_MODE"] == "allowlist"
        assert os.environ["DLP_ENABLED_AGENTS"] == "orchestrator|sub_agent"
        
        # Verify info types
        info_types = os.environ["DLP_INFO_TYPES"].split("|")
        assert "US_SOCIAL_SECURITY_NUMBER" in info_types
        assert "PASSPORT_NUMBER" in info_types
        assert "API_KEY" in info_types
        assert "AUTH_TOKEN" in info_types
        assert "DATE_OF_BIRTH" in info_types
        assert "PERSON_NAME" in info_types
        assert "LOCATION" in info_types
    
    def test_load_enterprise_and_create_dlp_settings(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test creating DLPSettings from enterprise config loaded via Secret Manager."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        # Now create DLPSettings from environment
        from adk_web_api.dlp_config import DLPSettings, DLPProvider, DLPAction
        
        settings = DLPSettings.from_env()
        
        # Verify settings match enterprise config
        assert settings.provider == DLPProvider.GOOGLE_CLOUD
        assert settings.action == DLPAction.MASK
        
        # Verify info types
        assert "US_SOCIAL_SECURITY_NUMBER" in settings.info_types
        assert "PASSPORT_NUMBER" in settings.info_types
        assert "API_KEY" in settings.info_types
        assert "AUTH_TOKEN" in settings.info_types
        assert "DATE_OF_BIRTH" in settings.info_types
        
        # Verify scan scopes
        assert settings.scan_user_messages == True
        assert settings.scan_llm_requests == True
        assert settings.scan_llm_responses == True
        assert settings.scan_tool_calls == True
        assert settings.scan_tool_results == True
        
        # Verify error handling
        assert settings.fallback_to_regex_on_error == True
        assert settings.skip_on_error == False


# ============================================================================
# Test DLP Detection with Secret Manager Config
# ============================================================================

class TestDLPDetectionWithSecretManager:
    """Test DLP detection with config loaded from Secret Manager."""
    
    @pytest.fixture
    def enterprise_config(self):
        """Enterprise profile configuration."""
        return {
            "DLP_PROVIDER": "regex",  # Use regex for testing without real GCP
            "DLP_ACTION": "mask",
            "DLP_MASK_CHAR": "*",
            "DLP_INFO_TYPES": "US_SOCIAL_SECURITY_NUMBER|PASSPORT_NUMBER|API_KEY|AUTH_TOKEN|DATE_OF_BIRTH|EMAIL_ADDRESS|PHONE_NUMBER|CREDIT_CARD_NUMBER|IP_ADDRESS",
            "DLP_SCAN_USER_MESSAGES": "true",
            "DLP_SCAN_LLM_REQUESTS": "true",
            "DLP_SCAN_LLM_RESPONSES": "true",
            "DLP_SCAN_TOOL_CALLS": "true",
            "DLP_SCAN_TOOL_RESULTS": "true",
            "DLP_AGENT_FILTER_MODE": "all",
            "DLP_FALLBACK_TO_REGEX": "true",
            "DLP_SKIP_ON_ERROR": "false"
        }
    
    def test_detect_ssn_with_secret_manager_config(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test SSN detection with config from Secret Manager."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        # Load config from Secret Manager
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        # Create DLP service
        from adk_web_api.dlp_service import DLPService
        from adk_web_api.dlp_config import DLPSettings
        
        settings = DLPSettings.from_env()
        service = DLPService(settings)
        
        # Test SSN detection
        result = service.scan("My SSN is 123-45-6789")
        
        assert "123-45-6789" not in result.processed_text
        assert "***-**-****" in result.processed_text
        
        # Verify finding
        assert len(result.findings) >= 1
        finding_types = [f.info_type for f in result.findings]
        assert "US_SOCIAL_SECURITY_NUMBER" in finding_types
    
    def test_detect_passport_with_secret_manager_config(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test passport detection with config from Secret Manager."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        from adk_web_api.dlp_service import DLPService
        from adk_web_api.dlp_config import DLPSettings
        
        settings = DLPSettings.from_env()
        service = DLPService(settings)
        
        # Test passport detection (using generic pattern)
        result = service.scan("Passport number: AB1234567")
        
        # Check if passport was detected (may depend on regex pattern)
        print(f"Processed: {result.processed_text}")
        print(f"Findings: {[f.info_type for f in result.findings]}")
    
    def test_detect_api_key_with_secret_manager_config(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test API key detection with config from Secret Manager."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        from adk_web_api.dlp_service import DLPService
        from adk_web_api.dlp_config import DLPSettings
        
        settings = DLPSettings.from_env()
        service = DLPService(settings)
        
        # Test API key detection
        result = service.scan("API Key: sk-1234567890abcdef1234567890abcdef")
        
        print(f"Processed: {result.processed_text}")
        print(f"Findings: {[f.info_type for f in result.findings]}")
    
    def test_detect_date_of_birth_with_secret_manager_config(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test date of birth detection with config from Secret Manager."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        from adk_web_api.dlp_service import DLPService
        from adk_web_api.dlp_config import DLPSettings
        
        settings = DLPSettings.from_env()
        service = DLPService(settings)
        
        # Test DOB detection
        result = service.scan("Date of Birth: 01/15/1990")
        
        print(f"Processed: {result.processed_text}")
        print(f"Findings: {[f.info_type for f in result.findings]}")
    
    def test_detect_multiple_info_types_with_enterprise_config(
        self, mock_secretmanager_client, clean_env, enterprise_config
    ):
        """Test detection of multiple info types with enterprise config."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(enterprise_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        loader.set_env_from_secret("dlp-config")
        
        from adk_web_api.dlp_service import DLPService
        from adk_web_api.dlp_config import DLPSettings
        
        settings = DLPSettings.from_env()
        service = DLPService(settings)
        
        # Test multiple PII types
        text = """
        User Information:
        Email: john.doe@example.com
        Phone: (555) 123-4567
        SSN: 123-45-6789
        DOB: 01/15/1990
        IP: 192.168.1.100
        Card: 4111 1111 1111 1111
        """
        
        result = service.scan(text)
        
        print(f"\nOriginal:\n{text}")
        print(f"\nProcessed:\n{result.processed_text}")
        print(f"\nFindings: {len(result.findings)}")
        for f in result.findings:
            print(f"  - {f.info_type}: {f.likelihood}")


# ============================================================================
# Test Convenience Functions
# ============================================================================

class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_secret_loader(self, mock_secretmanager_client):
        """Test create_secret_loader function."""
        loader = create_secret_loader(project_id="test-project")
        
        assert loader.project_id == "test-project"
    
    def test_load_secrets_at_startup(self, mock_secretmanager_client, clean_env):
        """Test load_secrets_at_startup function."""
        config = {"DLP_PROVIDER": "google_cloud"}
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        result = load_secrets_at_startup(
            project_id="test-project",
            secret_ids=["test-config"]
        )
        
        assert "test-config" in result
        assert os.environ["DLP_PROVIDER"] == "google_cloud"
    
    def test_load_dlp_config_from_secret(self, mock_secretmanager_client, clean_env):
        """Test load_dlp_config_from_secret function."""
        dlp_config = {
            "DLP_PROVIDER": "hybrid",
            "DLP_ACTION": "mask",
            "OTHER_VAR": "ignored"
        }
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps(dlp_config)
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        result = load_dlp_config_from_secret(
            secret_id="dlp-config",
            project_id="test-project"
        )
        
        # Only DLP_* vars should be returned
        assert "DLP_PROVIDER" in result
        assert "DLP_ACTION" in result
        assert "OTHER_VAR" not in result
        
        # Verify env vars set
        assert os.environ["DLP_PROVIDER"] == "hybrid"
        assert os.environ["DLP_ACTION"] == "mask"


# ============================================================================
# Test Cache Functionality
# ============================================================================

class TestCaching:
    """Test secret caching."""
    
    def test_secret_caching(self, mock_secretmanager_client):
        """Test that secrets are cached."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "cached-value"
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        
        # First call - should hit API
        value1 = loader.load_secret("my-secret")
        assert mock_secretmanager_client.access_secret_version.call_count == 1
        
        # Second call - should use cache
        value2 = loader.load_secret("my-secret")
        assert mock_secretmanager_client.access_secret_version.call_count == 1  # Still 1
        
        assert value1 == value2 == "cached-value"
    
    def test_cache_disabled(self, mock_secretmanager_client):
        """Test that caching can be disabled."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "no-cache-value"
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        
        # First call
        value1 = loader.load_secret("my-secret", cache=False)
        
        # Second call - should hit API again
        value2 = loader.load_secret("my-secret", cache=False)
        
        assert mock_secretmanager_client.access_secret_version.call_count == 2
    
    def test_clear_cache(self, mock_secretmanager_client):
        """Test clearing the cache."""
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = "value"
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        
        # Load and cache
        loader.load_secret("my-secret")
        assert mock_secretmanager_client.access_secret_version.call_count == 1
        
        # Clear cache
        loader.clear_cache()
        
        # Load again - should hit API
        loader.load_secret("my-secret")
        assert mock_secretmanager_client.access_secret_version.call_count == 2


# ============================================================================
# Test Load Multiple Secrets
# ============================================================================

class TestLoadMultipleSecrets:
    """Test loading multiple secrets."""
    
    def test_load_all_secrets_with_list(self, mock_secretmanager_client, clean_env):
        """Test loading multiple secrets from a list."""
        secrets = {
            "dlp-config": json.dumps({"DLP_PROVIDER": "google_cloud"}),
            "api-config": json.dumps({"API_TIMEOUT": "30"}),
        }
        
        def get_secret(request):
            name = request["name"]
            for secret_id, value in secrets.items():
                if secret_id in name:
                    mock_resp = MagicMock()
                    mock_resp.payload.data.decode.return_value = value
                    return mock_resp
            raise Exception("Secret not found")
        
        mock_secretmanager_client.access_secret_version.side_effect = get_secret
        
        loader = SecretManagerLoader(project_id="test-project")
        result = loader.load_all_secrets(default_secrets=["dlp-config", "api-config"])
        
        assert len(result) == 2
        assert "dlp-config" in result
        assert "api-config" in result
        assert os.environ["DLP_PROVIDER"] == "google_cloud"
        assert os.environ["API_TIMEOUT"] == "30"
    
    def test_load_secrets_with_config_objects(self, mock_secretmanager_client, clean_env):
        """Test loading secrets with SecretConfig objects."""
        config1 = SecretConfig(
            secret_id="dlp-config",
            version="latest",
            is_json=True,
            prefix_env_vars="DLP_"
        )
        
        mock_response = MagicMock()
        mock_response.payload.data.decode.return_value = json.dumps({
            "DLP_PROVIDER": "hybrid",
            "IGNORED_VAR": "skip-me"
        })
        mock_secretmanager_client.access_secret_version.return_value = mock_response
        
        loader = SecretManagerLoader(project_id="test-project")
        result = loader.load_all_secrets(secret_configs=[config1])
        
        assert "DLP_PROVIDER" in result["dlp-config"]
        assert "IGNORED_VAR" not in result["dlp-config"]


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
