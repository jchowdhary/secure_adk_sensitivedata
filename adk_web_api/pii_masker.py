"""Simple PII/Sensitive Data Masking Utility"""
import re
from typing import Callable

class PIIMasker:
    """Simple regex-based PII masker."""
    
    def __init__(self):
        """Initialize with common PII patterns."""
        self.patterns = {
            # Email: user@domain.com -> u***@domain.com
            'email': (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), 
                     lambda m: f"{m.group(0)[0]}***@{m.group(0).split('@')[1]}"),
            
            # Phone: (555) 123-4567 -> (***) ***-**** or 555-123-4567 -> ***-***-****
            'phone': (re.compile(r'(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),
                     lambda m: m.group(0).replace(m.group(0)[0 if m.group(0)[0].isdigit() else -4:], '***') if m.group(0).isdigit() else '(***) ***-****'),
            
            # SSN: 123-45-6789 -> ***-**-****
            'ssn': (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
                   lambda m: '***-**-****'),
            
            # Credit Card: 4111 1111 1111 1111 -> **** **** **** **** (masked each 4-digit block)
            'credit_card': (re.compile(r'\b(?:\d{4}[ -]?){3}\d{4}\b'),
                           lambda m: ' '.join(['****' for _ in m.group(0).split()])),
            
            # IP Address: 192.168.1.1 -> ***.**.**
            'ip': (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
                  lambda m: re.sub(r'\d{1,3}', '***', m.group(0))),
            
            # Generic identifiers (API keys, tokens): Matches alphanumeric strings with special chars
            'token': (re.compile(r'\b[A-Za-z0-9]{20,}\b|[A-Za-z0-9-]{20,}\b'),
                     lambda m: f"{m.group(0)[:8]}...***"),
        }
    
    def mask_text(self, text: str) -> str:
        """Mask all detected PII in the given text."""
        if not text:
            return text
        
        masked_text = text
        for pattern_name, (pattern, replacer) in self.patterns.items():
            masked_text = pattern.sub(replacer, masked_text)
        
        return masked_text


# Global instance for easy use
pii_masker = PIIMasker()

# Usage example:
if __name__ == "__main__":
    sample_text = "Contact me at john.doe@example.com or call (555) 123-4567."
    masked_text = pii_masker.mask_text(sample_text)
    print(f"Original: {sample_text}")
    print(f"Masked: {masked_text}")
    