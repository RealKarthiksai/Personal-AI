"""Structured logging helpers.

Logs include a request id and (when available) a message id so that the full
lifecycle of an incoming event can be traced. Secret values are never logged.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging with a structured, single-line format."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | req=%(request_id)s msg=%(message_id)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    # Add the request context filter to the root logger so ALL loggers inherit it.
    root.addFilter(RequestContextFilter())
    # Avoid duplicate handlers if re-configured.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)


class RequestContextFilter(logging.Filter):
    """Injects request_id and message_id into log records (default: '-')."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", "-")
        record.message_id = getattr(record, "message_id", "-")
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.addFilter(RequestContextFilter())
    return logger


def redact(value: Optional[str], keep: int = 4) -> str:
    """Return a redacted representation of a secret, never the full value."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "<redacted>"
    return f"<redacted:{value[-keep:]}>"