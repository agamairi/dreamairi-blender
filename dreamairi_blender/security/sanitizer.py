"""Redact secrets from logs."""
from __future__ import annotations

from typing import Iterable


import re

def redact(text: str, secrets: Iterable[str]) -> str:
    sanitized = text
    # Redact known secrets
    for secret in secrets:
        if secret and len(secret) > 3:
            sanitized = sanitized.replace(secret, "***")
    
    # Redact Authorization headers
    sanitized = re.sub(r'Authorization:\s*Bearer\s+\S+', 'Authorization: Bearer ***', sanitized, flags=re.IGNORECASE)
    # Redact API keys in URLs
    sanitized = re.sub(r'key=[a-zA-Z0-9_\-]+', 'key=***', sanitized)
    
    return sanitized
