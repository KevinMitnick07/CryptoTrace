"""
Tests for PII sanitization and secret redaction.
"""

import pytest

from backend.core.sanitizer import redact_secrets, sanitize_pii, sanitize_dict_records


def test_redact_home_paths():
    text = "Error occurred in file /Users/victim_user/Documents/secret_case.py on server"
    sanitized = redact_secrets(text)
    assert "/Users/victim_user" not in sanitized
    assert "[SYSTEM_PATH]" in sanitized


def test_sanitize_emails_and_phones():
    text = "Complainant email is victim.person@example.com and contact is +1 (555) 123-4567"
    sanitized = sanitize_pii(text)
    assert "victim.person@example.com" not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "555" not in sanitized
    assert "[REDACTED_PHONE]" in sanitized


def test_sanitize_nested_dict_secrets():
    payload = {
        "case_id": "CASE-101",
        "user_info": {
            "name": "Jane Doe",
            "email": "jane.doe@gmail.com",
            "api_key": "tron_secret_key_abcdef123456",
            "private_key": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        },
        "notes": "Contact phone +91 98765 43210 at /home/developer/app.log",
    }

    sanitized = sanitize_dict_records(payload)
    assert sanitized["user_info"]["api_key"] == "[REDACTED_CONFIDENTIAL]"
    assert sanitized["user_info"]["private_key"] == "[REDACTED_CONFIDENTIAL]"
    assert "[REDACTED_EMAIL]" in sanitized["user_info"]["email"]
    assert "/home/developer" not in sanitized["notes"]
    assert "[SYSTEM_PATH]" in sanitized["notes"]


def test_bearer_token_and_header_redaction():
    text = "Authorization: Bearer my_secret_token_123456 and TRON-PRO-API-KEY: key_998877"
    sanitized = redact_secrets(text)
    assert "my_secret_token_123456" not in sanitized
    assert "[REDACTED_AUTH_TOKEN]" in sanitized
    assert "key_998877" not in sanitized


def test_non_string_graceful_passthrough():
    assert sanitize_pii(12345) == 12345
    assert sanitize_dict_records(None) is None
    assert sanitize_dict_records(42) == 42
