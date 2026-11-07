"""Typed source exceptions and error mappers for Karna integrations.

Provides a unified taxonomy of source errors (unconfigured, rate_limited,
http_status, timeout, network) across GitHub, Reddit, OpenAlex, RSS, and Monitoring,
ensuring errors are never silently swallowed or misreported as empty results.
"""

from __future__ import annotations

from typing import Optional
import httpx

from app.utils.logging import get_logger

logger = get_logger("app.integrations.errors")


class SourceError(Exception):
    """Base exception for all external integration source failures."""

    def __init__(self, message: str, error_code: str = "internal"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

    def __str__(self) -> str:
        return self.message


class SourceUnconfigured(SourceError):
    """Raised when an external source requires credentials that are not configured."""

    def __init__(self, message: str = "Credentials not configured", source: Optional[str] = None):
        msg = f"{source}: {message}" if source else message
        super().__init__(msg, error_code="unconfigured")
        self.source = source


class SourceRateLimited(SourceError):
    """Raised when an external source rate limit is exceeded."""

    def __init__(
        self,
        retry_after: Optional[int] = None,
        message: str = "Rate limit exceeded",
        source: Optional[str] = None,
    ):
        msg = f"{source}: {message}" if source else message
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg, error_code="rate_limited")
        self.retry_after = retry_after
        self.source = source


class SourceHTTPError(SourceError):
    """Raised when an external HTTP request returns a 4xx or 5xx status code."""

    def __init__(self, status: int, message: str = "", source: Optional[str] = None):
        detail = message or f"HTTP {status}"
        msg = f"{source}: {detail}" if source else detail
        super().__init__(msg, error_code=f"http_{status}")
        self.status = status
        self.source = source


class SourceTimeout(SourceError):
    """Raised when an external request times out."""

    def __init__(self, message: str = "Request timed out", source: Optional[str] = None):
        msg = f"{source}: {message}" if source else message
        super().__init__(msg, error_code="timeout")
        self.source = source


class SourceNetworkError(SourceError):
    """Raised when network connectivity fails (DNS resolution, connection refused)."""

    def __init__(self, message: str = "Network connection failed", source: Optional[str] = None):
        msg = f"{source}: {message}" if source else message
        super().__init__(msg, error_code="network")
        self.source = source


def map_httpx_exception(exc: Exception, source: str) -> SourceError:
    """Map any HTTPX exception into a typed SourceError.

    Safely handles exceptions without leaking query parameters or tokens in logs.
    """
    if isinstance(exc, SourceError):
        return exc

    if isinstance(exc, httpx.TimeoutException):
        logger.warning("[%s] Request timed out", source)
        return SourceTimeout(message=f"Request to {source} timed out", source=source)

    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        logger.warning("[%s] Network connection failed", source)
        return SourceNetworkError(message=f"Network connection to {source} failed", source=source)

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        headers = exc.response.headers

        # Check for rate limiting headers (GitHub / Reddit / standard)
        rate_remaining = headers.get("x-ratelimit-remaining")
        retry_after_str = headers.get("retry-after")
        retry_after = int(retry_after_str) if (retry_after_str and retry_after_str.isdigit()) else None

        if status == 429 or rate_remaining == "0":
            logger.warning("[%s] Rate limit hit (status=%d, remaining=%s, retry_after=%s)", source, status, rate_remaining, retry_after)
            return SourceRateLimited(retry_after=retry_after, source=source)

        if status == 401:
            logger.warning("[%s] Unauthorized (HTTP 401)", source)
            return SourceHTTPError(status=401, message="Unauthorized (invalid token or credentials)", source=source)

        if status == 403:
            logger.warning("[%s] Forbidden (HTTP 403)", source)
            return SourceHTTPError(status=403, message="Forbidden (access denied or scope insufficient)", source=source)

        logger.warning("[%s] HTTP status error: %d", source, status)
        return SourceHTTPError(status=status, message=f"HTTP {status}", source=source)

    logger.error("[%s] Unexpected exception: %s", source, type(exc).__name__)
    return SourceError(f"Unexpected error in {source}", error_code="internal")
