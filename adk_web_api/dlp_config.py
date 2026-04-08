"""
DLP Configuration Module

This module provides configuration settings for Data Loss Prevention (DLP).
It supports both regex-based (local) and Google Cloud DLP detection methods.
"""
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class DLPProvider(Enum):
    """DLP provider options."""
    REGEX = "regex"  # Local regex-based detection
    GOOGLE_CLOUD = "google_cloud"  # Google Cloud DLP API
    HYBRID = "hybrid"  # Use both (Google Cloud first, regex fallback)


class DLPAction(Enum):
    """DLP action options."""
    MASK = "mask"  # Replace sensitive data with mask characters
    REDACT = "redact"  # Remove sensitive data completely
    REPLACE = "replace"  # Replace with custom string
    HASH = "hash"  # Replace with secure hash
    ALERT = "alert"  # Alert but don't modify


class AgentFilterMode(Enum):
    """Agent filtering mode options."""
    ALL = "all"  # Apply DLP to all agents (default)
    ALLOWLIST = "allowlist"  # Only apply DLP to agents in enabled_agents list
    BLOCKLIST = "blocklist"  # Apply DLP to all agents except those in disabled_agents list


@dataclass
class InfoTypeConfig:
    """Configuration for a specific info type."""
    name: str
    enabled: bool = True
    likelihood_threshold: str = "LIKELY"  # VERY_LIKELY, LIKELY, POSSIBLE, UNLIKELY
    custom_regex: Optional[str] = None  # For regex-based provider
    custom_replacement: Optional[str] = None  # Custom replacement string
    
    
@dataclass
class DLPSettings:
    """
    Comprehensive DLP settings.
    
    This configuration allows fine-grained control over:
    - Which DLP provider to use (regex, Google Cloud, or hybrid)
    - Which info types to detect
    - What action to take on detection
    - Scope of protection (user messages, LLM calls, tool calls)
    """
    
    # Provider configuration
    provider: DLPProvider = DLPProvider.REGEX
    google_cloud_project_id: Optional[str] = None
    google_cloud_credentials_path: Optional[str] = None
    
    # Action configuration
    action: DLPAction = DLPAction.MASK
    default_mask_char: str = "*"
    
    # Scope configuration - what to protect
    scan_user_messages: bool = True
    scan_llm_requests: bool = True
    scan_llm_responses: bool = True
    scan_tool_calls: bool = True
    scan_tool_results: bool = True
    
    # Agent filtering configuration - which agents to protect
    agent_filter_mode: AgentFilterMode = AgentFilterMode.ALL
    enabled_agents: List[str] = field(default_factory=list)  # Agents to scan (for ALLOWLIST mode)
    disabled_agents: List[str] = field(default_factory=list)  # Agents to skip (for BLOCKLIST mode)
    
    # Info types to detect
    info_types: List[str] = field(default_factory=lambda: [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SOCIAL_SECURITY_NUMBER",
        "CREDIT_CARD_NUMBER",
        "IP_ADDRESS",
        "PERSON_NAME",
        "LOCATION",
        "DATE_OF_BIRTH",
        "PASSPORT_NUMBER",
        "API_KEY",
        "AUTH_TOKEN",
    ])
    
    # Info type specific configurations
    info_type_configs: Dict[str, InfoTypeConfig] = field(default_factory=dict)
    
    # Performance settings
    max_bytes_per_request: int = 50000  # Max bytes to send to DLP API per request
    batch_processing: bool = False  # Batch multiple small texts together
    
    # Logging settings
    log_detections: bool = True
    log_detailed_findings: bool = True  # Log exact text found (set False for production)
    log_detections_to_cloud: bool = False  # Log to Cloud Logging

    # Email bypass settings
    enable_email_domain_bypass: bool = False
    bypass_email_domains: List[str] = field(default_factory=list)
    bypass_email_subdomains: bool = True
    
    # Error handling
    fallback_to_regex_on_error: bool = True  # If Google Cloud DLP fails, use regex
    skip_on_error: bool = False  # If True, skip text on error; if False, let through unmasked
    
    def __post_init__(self):
        """Initialize info type configurations."""
        # Set default configs for enabled info types
        for info_type in self.info_types:
            if info_type not in self.info_type_configs:
                self.info_type_configs[info_type] = InfoTypeConfig(name=info_type)
    
    def should_scan_agent(self, agent_name: str) -> bool:
        """
        Check if DLP should be applied to a specific agent.
        
        Args:
            agent_name: Name of the agent to check
            
        Returns:
            True if DLP should scan this agent, False otherwise
        """
        if self.agent_filter_mode == AgentFilterMode.ALL:
            return True
        elif self.agent_filter_mode == AgentFilterMode.ALLOWLIST:
            # Only scan if agent is in the enabled list
            return agent_name in self.enabled_agents
        elif self.agent_filter_mode == AgentFilterMode.BLOCKLIST:
            # Scan all agents except those in the disabled list
            return agent_name not in self.disabled_agents
        return True
    
    @classmethod
    def from_env(cls) -> 'DLPSettings':
        """Load settings from environment variables."""
        provider_str = os.getenv("DLP_PROVIDER", "regex").lower()
        provider = DLPProvider(provider_str) if provider_str in [p.value for p in DLPProvider] else DLPProvider.REGEX
        
        action_str = os.getenv("DLP_ACTION", "mask").lower()
        action = DLPAction(action_str) if action_str in [a.value for a in DLPAction] else DLPAction.MASK
        
        info_types_str = os.getenv("DLP_INFO_TYPES", "")
        info_types = [t.strip() for t in info_types_str.split("|") if t.strip()] if info_types_str else None
        
        # Default info types if not specified
        default_info_types = [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_SOCIAL_SECURITY_NUMBER",
            "CREDIT_CARD_NUMBER",
            "IP_ADDRESS",
        ]
        
        # Parse agent filter mode
        agent_filter_mode_str = os.getenv("DLP_AGENT_FILTER_MODE", "all").lower()
        agent_filter_mode = AgentFilterMode(agent_filter_mode_str) if agent_filter_mode_str in [m.value for m in AgentFilterMode] else AgentFilterMode.ALL
        
        # Parse enabled/disabled agents lists
        enabled_agents_str = os.getenv("DLP_ENABLED_AGENTS", "")
        enabled_agents = [a.strip() for a in enabled_agents_str.split("|") if a.strip()] if enabled_agents_str else []
        
        disabled_agents_str = os.getenv("DLP_DISABLED_AGENTS", "")
        disabled_agents = [a.strip() for a in disabled_agents_str.split("|") if a.strip()] if disabled_agents_str else []
        
        return cls(
            provider=provider,
            google_cloud_project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            google_cloud_credentials_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
            action=action,
            default_mask_char=os.getenv("DLP_MASK_CHAR", "*"),
            scan_user_messages=os.getenv("DLP_SCAN_USER_MESSAGES", "true").lower() == "true",
            scan_llm_requests=os.getenv("DLP_SCAN_LLM_REQUESTS", "true").lower() == "true",
            scan_llm_responses=os.getenv("DLP_SCAN_LLM_RESPONSES", "true").lower() == "true",
            scan_tool_calls=os.getenv("DLP_SCAN_TOOL_CALLS", "true").lower() == "true",
            scan_tool_results=os.getenv("DLP_SCAN_TOOL_RESULTS", "true").lower() == "true",
            agent_filter_mode=agent_filter_mode,
            enabled_agents=enabled_agents,
            disabled_agents=disabled_agents,
            info_types=info_types if info_types else default_info_types,
            fallback_to_regex_on_error=os.getenv("DLP_FALLBACK_TO_REGEX", "true").lower() == "true",
            skip_on_error=os.getenv("DLP_SKIP_ON_ERROR", "false").lower() == "true",
            enable_email_domain_bypass=os.getenv("DLP_ENABLE_EMAIL_DOMAIN_BYPASS", "true").lower() == "true",
            bypass_email_domains=[
                domain.strip().lower()
                for domain in os.getenv("DLP_BYPASS_EMAIL_DOMAINS", "ulta.com").split("|")
                if domain.strip()
            ],
            bypass_email_subdomains=os.getenv("DLP_BYPASS_EMAIL_SUBDOMAINS", "true").lower() == "true",
        )


# Predefined profiles for common use cases
class DLPProfiles:
    """Predefined DLP configuration profiles."""
    
    #DEFAULT_DLP_SETTINGS = DLPSettings()
    @staticmethod
    def _get_base() -> DLPSettings:
        """Helper to get a fresh copy of environment-based settings."""
        import copy
        return copy.deepcopy(DEFAULT_DLP_SETTINGS)    
    
    @staticmethod
    def basic() -> DLPSettings:
        """Basic profile - regex-based, minimal info types."""
        settings = DLPProfiles._get_base()
        settings.provider = DLPProvider.REGEX
        settings.info_types = ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER", "CREDIT_CARD_NUMBER"]
        return settings
    
    @staticmethod
    def standard() -> DLPSettings:
        """Standard profile - Google Cloud DLP with common info types."""
        settings = DLPProfiles._get_base()
        settings.provider = DLPProvider.GOOGLE_CLOUD
        settings.info_types = [
            "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER", 
            "CREDIT_CARD_NUMBER", "IP_ADDRESS", "PERSON_NAME", "LOCATION"
        ]
        settings.fallback_to_regex_on_error = True
        return settings
    
    @staticmethod
    def enterprise() -> DLPSettings:
        """Enterprise profile - Comprehensive protection."""
        settings = DLPProfiles._get_base()
        settings.provider = DLPProvider.GOOGLE_CLOUD
        settings.scan_user_messages = True
        settings.scan_llm_requests = True
        settings.scan_llm_responses = True
        settings.scan_tool_calls = True
        settings.scan_tool_results = True
        settings.info_types = [
            "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER",
            "CREDIT_CARD_NUMBER", "IP_ADDRESS", "PERSON_NAME", "LOCATION",
            "DATE_OF_BIRTH", "PASSPORT_NUMBER", "API_KEY", "AUTH_TOKEN",
            "US_BANK_ACCOUNT_NUMBER", "IBAN_CODE", "MEDICAL_TERM"
        ]
        settings.log_detections_to_cloud = True,
        settings.fallback_to_regex_on_error=True
        return settings
    
    @staticmethod
    def hybrid() -> DLPSettings:
        """
        Hybrid profile - Use both Google Cloud and regex.
        Inherits project ID and credentials from the environment.
        """
        settings = DLPProfiles._get_base()
        settings.provider = DLPProvider.HYBRID
        settings.fallback_to_regex_on_error = True
        
        # Comprehensive info types for a robust hybrid approach
        settings.info_types = [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_SOCIAL_SECURITY_NUMBER",
            "CREDIT_CARD_NUMBER",
            "IP_ADDRESS",
            "PERSON_NAME",
            "DATE_OF_BIRTH",
        ]
        
        return settings

# Export default settings
DEFAULT_DLP_SETTINGS = DLPSettings.from_env()
