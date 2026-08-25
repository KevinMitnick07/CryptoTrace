"""
Sanitization, secret redaction, and PII minimization layer.

Ensures that no API keys, private keys, seed phrases, local filesystem user paths,
or victim personal identification leak into API responses, audit logs, or evidence packages.
"""

from __future__ import annotations
import re
from typing import Any

# Redaction patterns
_HEX_PRIVATE_KEY = re.compile(r"\b(0x)?[0-9a-fA-F]{64}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b")
_BEARER_TOKEN = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE)
_API_KEY_HEADER = re.compile(r"(TRON-PRO-API-KEY|api-key|apikey|authorization):\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE)
_USER_HOME_PATH = re.compile(r"(/Users/[^/\s'\"]+|/home/[^/\s'\"]+|C:\\Users\\[^\\\s'\"]+)", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """Mask private keys, API tokens, and home directory paths from strings."""
    if not isinstance(text, str):
        return text

    # Redact home paths
    out = _USER_HOME_PATH.sub("[SYSTEM_PATH]", text)
    # Redact Bearer tokens
    out = _BEARER_TOKEN.sub("Bearer [REDACTED_AUTH_TOKEN]", out)
    # Redact API key header occurrences
    out = _API_KEY_HEADER.sub(r"\1: [REDACTED_KEY]", out)

    return out


def sanitize_pii(text: str, mask_emails: bool = True, mask_phones: bool = True) -> str:
    """Mask email addresses, phone numbers, and victim PII."""
    if not isinstance(text, str):
        return text

    out = text
    if mask_emails:
        out = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", out)
    if mask_phones:
        out = _PHONE_PATTERN.sub("[REDACTED_PHONE]", out)

    return redact_secrets(out)


def sanitize_dict_records(data: Any) -> Any:
    """Recursively sanitize dictionary and list values."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if any(secret_term in k.lower() for secret_term in ("secret", "api_key", "private_key", "password", "seed_phrase", "token")):
                sanitized[k] = "[REDACTED_CONFIDENTIAL]"
            else:
                sanitized[k] = sanitize_dict_records(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict_records(item) for item in data]
    elif isinstance(data, str):
        return sanitize_pii(data)
    else:
        return data
