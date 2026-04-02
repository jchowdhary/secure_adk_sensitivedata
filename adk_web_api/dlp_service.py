"""
DLP Service Module

Provides Data Loss Prevention capabilities including:
- Regex-based PII detection (local, fast)
- Google Cloud DLP API integration (accurate, enterprise-grade)
- Hybrid approach with fallback
"""
import re
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

from .dlp_config import DLPSettings, DLPProvider, DLPAction, InfoTypeConfig
from .logger import get_logger


@dataclass
class DLPMetadata:
    """Metadata for DLP finding."""
    info_type: str
    likelihood: str
    location_start: int
    location_end: int
    original_value: str
    masked_value: str


@dataclass
class DLPDetectionResult:
    """Result of DLP detection on a text."""
    original_text: str
    processed_text: str
    findings: List[DLPMetadata]
    was_modified: bool
    provider_used: str
    error: Optional[str] = None


class RegexDLPDetector:
    """Regex-based DLP detector for local, fast detection."""
    
    # Built-in regex patterns for common info types
    INFO_TYPE_PATTERNS = {
        "EMAIL_ADDRESS": {
            "pattern": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            "mask_template": lambda m: f"{m.group(0)[0]}***@{m.group(0).split('@')[1]}",
            "description": "Email address detection"
        },
        "PHONE_NUMBER": {
            "pattern": re.compile(r'(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
            "mask_template": lambda m: '(***) ***-****',
            "description": "Phone number detection"
        },
        "US_SOCIAL_SECURITY_NUMBER": {
            "pattern": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            "mask_template": lambda m: '***-**-****',
            "description": "US SSN detection"
        },
        "CREDIT_CARD_NUMBER": {
            "pattern": re.compile(r'\b(?:\d{4}[ -]?){3}\d{4}\b'),
            "mask_template": lambda m: '**** **** **** ****',
            "description": "Credit card number detection"
        },
        "IP_ADDRESS": {
            "pattern": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            "mask_template": lambda m: re.sub(r'\d{1,3}', '***', m.group(0)),
            "description": "IP address detection"
        },
        "API_KEY": {
            "pattern": re.compile(r'\b(?:api[_-]?key|apikey)[_-]?[A-Za-z0-9]{16,}\b', re.IGNORECASE),
            "mask_template": lambda m: f"{m.group(0)[:8]}...***",
            "description": "API key detection"
        },
        "AUTH_TOKEN": {
            "pattern": re.compile(r'\b(?:token|bearer|auth)[_-]?[A-Za-z0-9]{20,}\b', re.IGNORECASE),
            "mask_template": lambda m: f"{m.group(0)[:8]}...***",
            "description": "Auth token detection"
        },
        "DATE_OF_BIRTH": {
            "pattern": re.compile(r'\b(?:DOB|dob|birth|birthday)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', re.IGNORECASE),
            "mask_template": lambda m: m.group(0).replace(m.group(1), '**/**/****'),
            "description": "Date of birth detection"
        },
        "PASSPORT_NUMBER": {
            "pattern": re.compile(r'\b[A-Z]{1,2}\d{6,9}\b'),
            "mask_template": lambda m: '*******',
            "description": "Passport number detection (generic)"
        },
        "US_DRIVER_LICENSE_NUMBER": {
            "pattern": re.compile(r'\b[A-Z]\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{3}\b|\b[A-Z]{1,2}\d{5,8}\b'),
            "mask_template": lambda m: '********',
            "description": "US Driver license detection (generic)"
        },
    }
    
    def __init__(self, settings: DLPSettings):
        """Initialize regex detector with settings."""
        self.settings = settings
        self.logger = get_logger()
        
        # Build patterns from settings
        self.enabled_patterns: Dict[str, Any] = {}
        for info_type in settings.info_types:
            if info_type in self.INFO_TYPE_PATTERNS:
                pattern_config = self.INFO_TYPE_PATTERNS[info_type]
                
                # Check if there's a custom config
                info_type_config = settings.info_type_configs.get(info_type)
                
                # Use custom regex if provided
                if info_type_config and info_type_config.custom_regex:
                    pattern = re.compile(info_type_config.custom_regex)
                else:
                    pattern = pattern_config["pattern"]
                
                self.enabled_patterns[info_type] = {
                    "pattern": pattern,
                    "mask_template": pattern_config["mask_template"],
                    "config": info_type_config
                }
    
    def detect(self, text: str) -> DLPDetectionResult:
        """Detect PII using regex patterns."""
        findings = []
        processed_text = text
        
        for info_type, pattern_config in self.enabled_patterns.items():
            pattern = pattern_config["pattern"]
            config = pattern_config.get("config")
            
            if config and not config.enabled:
                continue
            
            # Find all matches
            matches = list(pattern.finditer(text))
            for match in matches:
                original_value = match.group(0)
                
                # Generate masked value based on action
                if self.settings.action == DLPAction.MASK:
                    masked_value = pattern_config["mask_template"](match)
                elif self.settings.action == DLPAction.REDACT:
                    masked_value = ""
                elif self.settings.action == DLPAction.REPLACE:
                    masked_value = config.custom_replacement if config and config.custom_replacement else "[REDACTED]"
                elif self.settings.action == DLPAction.HASH:
                    masked_value = hashlib.sha256(original_value.encode()).hexdigest()[:8] + "...***"
                else:  # ALERT
                    masked_value = original_value
                
                findings.append(DLPMetadata(
                    info_type=info_type,
                    likelihood="LIKELY",  # Regex detection doesn't have likelihood
                    location_start=match.start(),
                    location_end=match.end(),
                    original_value=original_value if self.settings.log_detailed_findings else "***",
                    masked_value=masked_value
                ))
        
        # Apply masking to text
        if self.settings.action != DLPAction.ALERT and findings:
            # Sort findings by position (reverse order for replacement)
            sorted_findings = sorted(findings, key=lambda f: f.location_start, reverse=True)
            processed_text = text
            for finding in sorted_findings:
                processed_text = (
                    processed_text[:finding.location_start] + 
                    finding.masked_value + 
                    processed_text[finding.location_end:]
                )
        
        return DLPDetectionResult(
            original_text=text,
            processed_text=processed_text,
            findings=findings,
            was_modified=len(findings) > 0,
            provider_used="regex"
        )


class GoogleCloudDLPDetector:
    """Google Cloud DLP API detector for enterprise-grade detection."""
    
    def __init__(self, settings: DLPSettings):
        """Initialize Google Cloud DLP detector."""
        self.settings = settings
        self.logger = get_logger()
        
        # Initialize DLP client if Google Cloud is configured
        self._client = None
        self._initialized = False
        
    def _initialize_client(self):
        """Lazy initialization of DLP client."""
        if self._initialized:
            return self._client is not None
        
        try:
            from google.cloud import dlp_v2
            from google.oauth2 import service_account
            
            # Initialize credentials
            if self.settings.google_cloud_credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    self.settings.google_cloud_credentials_path
                )
                self._client = dlp_v2.DlpServiceClient(credentials=credentials)
            else:
                # Use default credentials
                self._client = dlp_v2.DlpServiceClient()
            
            self.logger.success("Google Cloud DLP client initialized")
            self._initialized = True
            return True
            
        except ImportError as e:
            self.logger.warning("google-cloud-dlp not installed. Install with: pip install google-cloud-dlp")
            self._initialized = True
            return False
        except Exception as e:
            self.logger.error("Failed to initialize Google Cloud DLP client", error=e)
            self._initialized = True
            return False
    
    def detect(self, text: str) -> DLPDetectionResult:
        """Detect PII using Google Cloud DLP API."""
        if not self._initialize_client():
            # Client initialization failed
            return DLPDetectionResult(
                original_text=text,
                processed_text=text,
                findings=[],
                was_modified=False,
                provider_used="google_cloud",
                error="DLP client initialization failed"
            )
        
        try:
            from google.cloud import dlp_v2
            from google.cloud.dlp_v2 import types as dlp_types
            
            # Build the request
            project_id = self.settings.google_cloud_project_id
            
            # Convert info types to DLP format
            info_types = [{"name": info_type} for info_type in self.settings.info_types]
            
            # Build inspect config
            inspect_config = {
                "info_types": info_types,
                "include_quote": self.settings.log_detailed_findings,
                "min_likelihood": dlp_v2.Likelihood.LIKELY,
            }
            
            # Build deidentify config based on action
            if self.settings.action == DLPAction.MASK:
                deidentify_config = {
                    "info_type_transformations": {
                        "transformations": [
                            {
                                "info_types": info_types,
                                "primitive_transformation": {
                                    "character_mask_config": {
                                        "masking_character": self.settings.default_mask_char,
                                        "number_to_mask": 0,  # Mask all
                                    }
                                }
                            }
                        ]
                    }
                }
            elif self.settings.action == DLPAction.REDACT:
                deidentify_config = {
                    "info_type_transformations": {
                        "transformations": [
                            {
                                "info_types": info_types,
                                "primitive_transformation": {
                                    "redact_config": {}
                                }
                            }
                        ]
                    }
                }
            elif self.settings.action == DLPAction.REPLACE:
                deidentify_config = {
                    "info_type_transformations": {
                        "transformations": [
                            {
                                "info_types": info_types,
                                "primitive_transformation": {
                                    "replace_config": {
                                        "new_value": {"string_value": "[REDACTED]"}
                                    }
                                }
                            }
                        ]
                    }
                }
            else:
                deidentify_config = None
            
            # Build the content item
            content_item = {"value": text}
            
            # Make the API call
            if deidentify_config:
                # Deidentify content (detect and mask)
                response = self._client.deidentify_content(
                    request={
                        "parent": f"projects/{project_id}",
                        "deidentify_config": deidentify_config,
                        "inspect_config": inspect_config,
                        "item": content_item,
                    }
                )
                
                processed_text = response.item.value
                findings = self._parse_findings(response.details.results[0].findings, text)
            else:
                # Only inspect (for ALERT action)
                response = self._client.inspect_content(
                    request={
                        "parent": f"projects/{project_id}",
                        "inspect_config": inspect_config,
                        "item": content_item,
                    }
                )
                
                processed_text = text
                findings = self._parse_findings(response.result.findings, text)
            
            return DLPDetectionResult(
                original_text=text,
                processed_text=processed_text,
                findings=findings,
                was_modified=text != processed_text,
                provider_used="google_cloud"
            )
            
        except Exception as e:
            self.logger.error("Google Cloud DLP detection failed", error=e)
            return DLPDetectionResult(
                original_text=text,
                processed_text=text,
                findings=[],
                was_modified=False,
                provider_used="google_cloud",
                error=str(e)
            )
    
    def _parse_findings(self, findings_response, original_text: str) -> List[DLPMetadata]:
        """Parse DLP API findings into metadata."""
        findings = []
        
        for finding in findings_response:
            info_type = finding.info_type.name
            likelihood = dlp_v2.Likelihood.Name(finding.likelihood)
            
            # Get location
            location_start = finding.location.byte_range.start
            location_end = finding.location.byte_range.end
            
            original_value = original_text[location_start:location_end] if self.settings.log_detailed_findings else "***"
            
            findings.append(DLPMetadata(
                info_type=info_type,
                likelihood=likelihood,
                location_start=location_start,
                location_end=location_end,
                original_value=original_value,
                masked_value=""  # Will be populated after processing
            ))
        
        return findings


class DLPService:
    """
    Main DLP Service that provides a unified interface for PII detection.
    
    Supports:
    - Regex-based detection (local, fast)
    - Google Cloud DLP (accurate, enterprise-grade)
    - Hybrid approach with fallback
    """
    
    def __init__(self, settings: Optional[DLPSettings] = None):
        """Initialize DLP service with settings."""
        self.settings = settings or DLPSettings.from_env()
        self.logger = get_logger()
        
        # Initialize detectors based on provider
        self._regex_detector: Optional[RegexDLPDetector] = None
        self._google_cloud_detector: Optional[GoogleCloudDLPDetector] = None
        
        if self.settings.provider in [DLPProvider.REGEX, DLPProvider.HYBRID]:
            self._regex_detector = RegexDLPDetector(self.settings)
        
        if self.settings.provider in [DLPProvider.GOOGLE_CLOUD, DLPProvider.HYBRID]:
            self._google_cloud_detector = GoogleCloudDLPDetector(self.settings)
    
    def scan(self, text: str, context: str = "") -> DLPDetectionResult:
        """
        Scan text for PII based on configured provider.
        
        Args:
            text: Text to scan
            context: Context for logging (e.g., "user_message", "llm_response")
        
        Returns:
            DLPDetectionResult with findings and processed text
        """
        if not text:
            return DLPDetectionResult(
                original_text=text,
                processed_text=text,
                findings=[],
                was_modified=False,
                provider_used="none"
            )
        
        self.logger.debug(f"DLP scan started - Context: {context}, Provider: {self.settings.provider.value}")
        self.logger.indent()
        
        result = None
        
        try:
            if self.settings.provider == DLPProvider.REGEX:
                result = self._regex_detector.detect(text)
            
            elif self.settings.provider == DLPProvider.GOOGLE_CLOUD:
                result = self._google_cloud_detector.detect(text)
                
                # Check if Google Cloud failed and we should fallback
                if result.error and self.settings.fallback_to_regex_on_error:
                    self.logger.warning(f"Google Cloud DLP failed, falling back to regex: {result.error}")
                    result = self._regex_detector.detect(text)
            
            elif self.settings.provider == DLPProvider.HYBRID:
                # Try Google Cloud first
                result = self._google_cloud_detector.detect(text)
                
                # If Google Cloud failed or had an error, use regex
                if result.error or not result.was_modified:
                    self.logger.debug("Trying regex as fallback/verification")
                    regex_result = self._regex_detector.detect(text)
                    
                    # Combine findings from both
                    if result.error:
                        result = regex_result
                    elif regex_result.was_modified:
                        # Merge findings
                        combined_findings = result.findings + [
                            f for f in regex_result.findings 
                            if f.info_type not in [rf.info_type for rf in result.findings]
                        ]
                        result.findings = combined_findings
                        result.was_modified = len(combined_findings) > 0
            
            # Log the results
            if result.was_modified:
                self.logger.success(f"DLP scan found {len(result.findings)} finding(s)")
                self.logger.before_after(
                    f"DLP Processing ({context})",
                    result.original_text,
                    result.processed_text,
                    changed=True
                )
                
                # Log findings
                for finding in result.findings:
                    self.logger.info(
                        f"Found {finding.info_type}",
                        details=f"Likelihood: {finding.likelihood}"
                    )
            else:
                self.logger.debug("No PII detected")
        
        except Exception as e:
            self.logger.error(f"DLP scan failed for context: {context}", error=e)
            
            # Handle error based on settings
            if self.settings.fallback_to_regex_on_error and self._regex_detector:
                self.logger.warning("Falling back to regex due to error")
                result = self._regex_detector.detect(text)
            elif self.settings.skip_on_error:
                result = DLPDetectionResult(
                    original_text=text,
                    processed_text="[DLP_ERROR]",
                    findings=[],
                    was_modified=True,
                    provider_used="error",
                    error=str(e)
                )
            else:
                # Let text through unmasked
                result = DLPDetectionResult(
                    original_text=text,
                    processed_text=text,
                    findings=[],
                    was_modified=False,
                    provider_used="error",
                    error=str(e)
                )
        
        self.logger.dedent()
        return result
    
    def scan_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[DLPMetadata]]:
        """
        Scan tool call arguments for PII.
        
        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments to the tool
        
        Returns:
            Tuple of (masked_args, findings)
        """
        if not self.settings.scan_tool_calls:
            return tool_args, []
        
        findings = []
        masked_args = {}
        
        for key, value in tool_args.items():
            if isinstance(value, str):
                result = self.scan(value, context=f"tool_call:{tool_name}.{key}")
                masked_args[key] = result.processed_text
                findings.extend(result.findings)
            else:
                masked_args[key] = value
        
        return masked_args, findings