"""
Google Secret Manager Integration

This module provides utilities to load environment variables and configuration
from Google Cloud Secret Manager, enabling dynamic configuration updates
without redeploying to Cloud Run.

Usage:
    # At application startup, load all secrets
    from adk_web_api.secret_manager import SecretManagerLoader
    
    loader = SecretManagerLoader(project_id="my-project")
    loader.load_all_secrets()  # Loads secrets into os.environ
    
    # Or load specific secret as JSON
    config = loader.load_secret_as_json("dlp-config")
"""

import os
import json
import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass

# Google Cloud Parameter Manager
try:
    from google.cloud import parametermanager_v1
    from google.api_core import exceptions as gcp_exceptions
    SECRET_MANAGER_AVAILABLE = True
except ImportError:
    SECRET_MANAGER_AVAILABLE = False
    parametermanager_v1 = None
    gcp_exceptions = None


logger = logging.getLogger(__name__)


@dataclass
class SecretConfig:
    """Configuration for a single secret."""
    secret_id: str
    version: str = "new"
    is_json: bool = False
    prefix_env_vars: Optional[str] = None  # e.g., "DLP_" for DLP_* variables


class SecretManagerLoader:
    """
    Load secrets from Google Cloud Secret Manager and set them as environment variables.
    
    This enables:
    - Dynamic configuration updates without redeployment
    - Centralized secret management
    - Version control for secrets
    
    Environment Variables:
        GOOGLE_CLOUD_PROJECT: GCP project ID (required if not passed to constructor)
        SECRET_VERSION: Default version to use (default: "new")
    """
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
    ):
        """
        Initialize the Secret Manager loader.
        
        Args:
            project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT env var.
            credentials_path: Path to service account JSON. Falls back to 
                             GOOGLE_APPLICATION_CREDENTIALS env var.
        """
        if not SECRET_MANAGER_AVAILABLE:
            raise ImportError(
                "google-cloud-parametermanager is not installed. "
                "Install it with: pip install google-cloud-parametermanager"
            )
        
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not self.project_id:
            raise ValueError(
                "Project ID is required. Set GOOGLE_CLOUD_PROJECT env var "
                "or pass project_id parameter."
            )
        
        # Initialize Secret Manager client
        client_kwargs = {}
        if credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            # Credentials will be picked up automatically from env var
            pass
        
        self.client = parametermanager_v1.ParameterManagerClient()
        self._cache: Dict[str, Any] = {}
        
        logger.info(f"SecretManagerLoader initialized for project: {self.project_id}")
    
    def _get_secret_path(self, secret_id: str, version: str = "new") -> str:
        """Build the secret resource path."""
        return f"projects/{self.project_id}/locations/global/parameters/{secret_id}/versions/{version}"
    
    def load_secret(
        self,
        secret_id: str,
        version: str = "new",
        cache: bool = True
    ) -> str:
        """
        Load a secret value from Secret Manager.
        
        Args:
            secret_id: The ID of the secret (not the full path)
            version: Version to load (default: "new")
            cache: Whether to cache the result
            
        Returns:
            The secret value as a string
        """
        cache_key = f"{secret_id}:{version}"
        
        if cache and cache_key in self._cache:
            logger.debug(f"Returning cached secret: {secret_id}")
            return self._cache[cache_key]
        
        try:
            name = self._get_secret_path(secret_id, version)
            logger.info(f"Loading secret: {secret_id} (version: {version})")
            
            response = self.client.get_parameter_version(request={"name": name})
            value = response.payload.data.decode("UTF-8")
            
            if cache:
                self._cache[cache_key] = value
            
            logger.info(f"Successfully loaded secret: {secret_id}")
            return value
            
        except gcp_exceptions.NotFound as e:
            logger.error(f"Secret not found: {secret_id}")
            raise ValueError(f"Secret '{secret_id}' not found in project '{self.project_id}'") from e
        except gcp_exceptions.PermissionDenied as e:
            logger.error(f"Permission denied accessing secret: {secret_id}")
            raise PermissionError(
                f"Permission denied for secret '{secret_id}'. "
                f"Ensure the service account has 'roles/secretmanager.secretAccessor' role."
            ) from e
        except Exception as e:
            logger.error(f"Error loading secret {secret_id}: {e}")
            raise
    
    def load_secret_as_json(
        self,
        secret_id: str,
        version: str = "new",
        cache: bool = True
    ) -> Dict[str, Any]:
        """
        Load a secret and parse it as JSON.
        
        Args:
            secret_id: The ID of the secret
            version: Version to load (default: "new")
            cache: Whether to cache the result
            
        Returns:
            Parsed JSON as a dictionary
        """
        value = self.load_secret(secret_id, version, cache)
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse secret {secret_id} as JSON: {e}")
            raise ValueError(f"Secret '{secret_id}' is not valid JSON") from e
    
    def set_env_from_secret(
        self,
        secret_id: str,
        version: str = "new",
        prefix_filter: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Load a secret (as JSON) and set each key-value pair as environment variables.
        
        Args:
            secret_id: The ID of the secret (should contain JSON)
            version: Version to load
            prefix_filter: Only set env vars that start with this prefix 
                          (e.g., "DLP_" for DLP_* variables)
        
        Returns:
            Dictionary of env vars that were set
        """
        data = self.load_secret_as_json(secret_id, version)
        set_vars = {}
        
        for key, value in data.items():
            if prefix_filter and not key.startswith(prefix_filter):
                continue
            
            # Convert value to string if it's not already
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            elif value is None:
                value = ""
            elif isinstance(value, bool):
                value = str(value).lower()
            else:
                value = str(value)
            
            os.environ[key] = value
            set_vars[key] = value
            logger.debug(f"Set env var: {key}")
        
        logger.info(f"Set {len(set_vars)} environment variables from secret: {secret_id}")
        return set_vars
    
    def load_all_secrets(
        self,
        secret_configs: Optional[List[SecretConfig]] = None,
        default_secrets: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, str]]:
        """
        Load multiple secrets and set them as environment variables.
        
        Args:
            secret_configs: List of SecretConfig objects for detailed control
            default_secrets: Simple list of secret IDs to load as JSON env vars
        
        Returns:
            Dictionary mapping secret_id -> dict of env vars set
        """
        results = {}
        
        # Use default secrets if no configs provided
        if secret_configs is None and default_secrets is None:
            default_secrets = self._get_default_secrets()
        
        if secret_configs:
            for config in secret_configs:
                if config.is_json:
                    vars_set = self.set_env_from_secret(
                        config.secret_id,
                        config.version,
                        config.prefix_env_vars
                    )
                    results[config.secret_id] = vars_set
                else:
                    value = self.load_secret(config.secret_id, config.version)
                    os.environ[config.secret_id] = value
                    results[config.secret_id] = {config.secret_id: value}
        
        if default_secrets:
            for secret_id in default_secrets:
                try:
                    vars_set = self.set_env_from_secret(secret_id)
                    results[secret_id] = vars_set
                except ValueError as e:
                    # Not JSON, treat as single value
                    value = self.load_secret(secret_id)
                    os.environ[secret_id] = value
                    results[secret_id] = {secret_id: value}
        
        logger.info(f"Loaded {len(results)} secrets into environment")
        return results
    
    def _get_default_secrets(self) -> List[str]:
        """
        Get default list of secrets to load based on environment.
        
        Override this method or use DEFAULT_SECRETS env var for customization.
        """
        default_secrets_str = os.getenv("DEFAULT_SECRETS", "")
        if default_secrets_str:
            return [s.strip() for s in default_secrets_str.split(",") if s.strip()]
        return []
    
    def clear_cache(self):
        """Clear the internal cache."""
        self._cache.clear()
        logger.debug("Secret cache cleared")


# ============================================================================
# Convenience Functions
# ============================================================================

def create_secret_loader(
    project_id: Optional[str] = None,
    credentials_path: Optional[str] = None
) -> SecretManagerLoader:
    """
    Create a SecretManagerLoader instance.
    
    This is a convenience function for quick setup.
    """
    return SecretManagerLoader(project_id, credentials_path)


def load_secrets_at_startup(
    project_id: Optional[str] = None,
    secret_ids: Optional[List[str]] = None
) -> Dict[str, Dict[str, str]]:
    """
    Load secrets at application startup.
    
    Call this at the beginning of your main.py before importing other modules.
    
    Args:
        project_id: GCP project ID
        secret_ids: List of secret IDs to load
        
    Returns:
        Dictionary of loaded secrets
    """
    loader = SecretManagerLoader(project_id)
    return loader.load_all_secrets(default_secrets=secret_ids)


# ============================================================================
# DLP-Specific Secret Loading
# ============================================================================

def load_dlp_config_from_secret(
    secret_id: str = "dlp-config",
    project_id: Optional[str] = None
) -> Dict[str, str]:
    """
    Load DLP configuration from Secret Manager.
    
    Expected secret format (JSON):
    {
        "DLP_PROVIDER": "regex",
        "DLP_ACTION": "mask",
        "DLP_MASK_CHAR": "*",
        "DLP_INFO_TYPES": "EMAIL_ADDRESS|PHONE_NUMBER|US_SOCIAL_SECURITY_NUMBER",
        "DLP_SCAN_USER_MESSAGES": "true",
        "DLP_SCAN_LLM_REQUESTS": "true",
        "DLP_SCAN_LLM_RESPONSES": "true",
        "DLP_SCAN_TOOL_CALLS": "true",
        "DLP_SCAN_TOOL_RESULTS": "true",
        "DLP_AGENT_FILTER_MODE": "all",
        "DLP_ENABLED_AGENTS": "orchestrator|sub_agent",
        "DLP_DISABLED_AGENTS": "public-agent|external-agent",
        "DLP_FALLBACK_TO_REGEX": "true",
        "DLP_SKIP_ON_ERROR": "false"
    }
    
    Args:
        secret_id: Secret ID in Secret Manager (default: "dlp-config")
        project_id: GCP project ID
        
    Returns:
        Dictionary of DLP env vars that were set
    """
    loader = SecretManagerLoader(project_id)
    return loader.set_env_from_secret(secret_id, prefix_filter="DLP_")


# ============================================================================
# Example: Main Application Startup
# ============================================================================

"""
# In your main.py:

import os
from dotenv import load_dotenv

# First, load .env for local development (won't override existing env vars)
load_dotenv()

# Then, load secrets from Secret Manager (will override .env values)
if os.getenv("GOOGLE_CLOUD_PROJECT"):
    from adk_web_api.secret_manager import load_secrets_at_startup
    
    # Define secrets to load
    secrets_to_load = [
        "dlp-config",        # DLP configuration
        "adk-config",        # ADK/agent configuration
        "api-keys",          # API keys
    ]
    
    loaded = load_secrets_at_startup(secret_ids=secrets_to_load)
    print(f"Loaded {len(loaded)} secrets from Secret Manager")

# Now import modules that use these env vars
from adk_web_api.dlp_plugin import create_dlp_plugin
# ... rest of your code
"""
