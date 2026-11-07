"""Secret and sensitive data redaction for the memory subsystem."""

from __future__ import annotations

import re
from typing import Tuple

# Regex patterns for common secrets and high-risk PII
PATTERNS = [
    # API Keys & Tokens (Bearer tokens, OpenAI/Anthropic/GitHub/HuggingFace/AWS/Slack tokens)
    (re.compile(r"(?i)\b(?:bearer\s+)?(?:sk-[a-zA-Z0-9_\-]{20,}|gh[pousr]_[a-zA-Z0-9]{20,}|hf_[a-zA-Z0-9]{20,}|akia[0-9a-z]{16}|xox[baprs]-[0-9a-zA-Z]{10,})\b"), "[REDACTED_API_KEY]"),
    # Generic high-entropy hex/base64 tokens in key=val or 'is' formats (including punctuation in passwords)
    (re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|auth[_-]?token)\s*(?:is|:|=)\s*['\"]?([^\s'\"]{6,})['\"]?"), "[REDACTED_PASSWORD]"),
    # Credit Card Numbers (13-19 digits, with optional hyphens or spaces)
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "[REDACTED_CARD]"),
    # OTPs / PINs (e.g. "otp is 123456", "verification code 654321")
    (re.compile(r"(?i)\b(?:otp|one-time\s+pass(?:word)?|verification\s+code)\s*(?:is|:)?\s*(\d{4,8})\b"), "[REDACTED_OTP]"),
    # Common Government IDs (US SSN, Indian Aadhaar, Indian PAN)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), "[REDACTED_AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"), "[REDACTED_PAN]"),
]


def redact_sensitive_text(text: str) -> str:
    """Scrub passwords, tokens, API keys, card numbers, and government IDs."""
    if not text:
        return ""
    clean = text
    for pattern, replacement in PATTERNS:
        clean = pattern.sub(replacement, clean)
    return clean


def is_sensitive_category(category: str, is_explicit: bool = False) -> bool:
    """Check if category is considered sensitive (health, finance, biometric).

    Sensitive categories are rejected unless explicitly requested by the user.
    """
    cat = category.strip().lower()
    if cat in ("health", "medical", "finance", "banking", "financial", "biometric", "credentials"):
        return not is_explicit
    return False
