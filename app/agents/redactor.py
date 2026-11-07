"""Secret scrubber and ANSI control sequence stripper for agent output and logs."""

from __future__ import annotations

import re
from typing import Pattern

# Regex to strip ANSI escape codes and terminal control sequences
ANSI_ESCAPE_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Patterns for sensitive credentials to redact
SECRET_PATTERNS: list[tuple[Pattern[str], str]] = [
    # Authorization: Bearer / Basic
    (
        re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s\r\n]+"),
        r"\1[REDACTED_AUTH_TOKEN]",
    ),
    # OpenAI / Anthropic / Generic API keys
    (
        re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"),
        "[REDACTED_API_KEY]",
    ),
    # Antigravity API key / Google AI key
    (
        re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b"),
        "[REDACTED_GOOGLE_API_KEY]",
    ),
    # Telegram Bot Token (digits:alphanumeric)
    (
        re.compile(r"\b(\d{8,11}:[a-zA-Z0-9_\-]{30,50})\b"),
        "[REDACTED_TELEGRAM_TOKEN]",
    ),
    # Private Key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # .env style secret assignments: ANY_KEY_NAME=value
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_]*(?:token|api_key|secret|password|auth_token|access_token|private_key|database_url)\s*=\s*)(['\"]?)[^\r\n'\"]+\2"
        ),
        r"\1\2[REDACTED_CREDENTIAL]\2",
    ),
    # JSON style secret fields: "password": "...", "token": "..."
    (
        re.compile(
            r"(?i)(\"(?:token|api_key|password|secret|key|access_token)\"\s*:\s*\")[^\"]+(\")"
        ),
        r"\1[REDACTED_SECRET]\2",
    ),
]


def strip_ansi(text: str) -> str:
    """Remove terminal ANSI escape codes and cursor manipulation sequences."""
    if not text:
        return ""
    return ANSI_ESCAPE_REGEX.sub("", text)


def redact_secrets(text: str) -> str:
    """Scrub known secret formats, tokens, passwords, and authorization headers from text."""
    if not text:
        return ""
    scrubbed = text
    for pattern, replacement in SECRET_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def clean_agent_output(text: str) -> str:
    """Combined ANSI stripping and secret redaction pipeline."""
    return redact_secrets(strip_ansi(text))
