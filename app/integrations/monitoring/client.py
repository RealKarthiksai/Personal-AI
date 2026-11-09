"""Website change detection and monitoring client.

Supports both ChangeDetection.io REST API and native differential content hashing.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional
import httpx

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.integrations.monitoring.client")

HTML_TAG_RE = re.compile(r"<[^>]+>")


def extract_clean_text(html: str) -> str:
    """Extract plain text from HTML, removing script/style and normalizing whitespace."""
    # Remove script and style elements
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = HTML_TAG_RE.sub(" ", cleaned)
    return " ".join(cleaned.split()).strip()


class ChangeDetectionClient:
    """Client for monitoring web pages for content modifications."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or config.changedetection_base_url or "").rstrip("/")
        self.api_key = api_key if api_key is not None else config.changedetection_api_key
        self.timeout = timeout

    def is_remote_configured(self) -> bool:
        """Check if external ChangeDetection.io instance is configured."""
        return bool(self.base_url)

    def _get_headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "KarnaChangeMonitor/1.0"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def fetch_page_raw(self, url: str) -> str:
        """Fetch webpage and return raw HTML text."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    async def fetch_page_content(self, url: str) -> str:
        """Fetch webpage and return clean plain text."""
        raw = await self.fetch_page_raw(url)
        return extract_clean_text(raw)

    def compute_hash(self, text: str) -> str:
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def create_remote_watch(self, url: str, tag: Optional[str] = None) -> Optional[str]:
        """Create a watch on a remote ChangeDetection.io instance if configured."""
        if not self.is_remote_configured():
            return None

        endpoint = f"{self.base_url}/api/v1/watch"
        payload = {"url": url, "tag": tag or "karna"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=self._get_headers())
                resp.raise_for_status()
                data = resp.json()
                return data.get("uuid")
        except Exception as exc:
            logger.warning("Failed to create watch on ChangeDetection.io: %s", exc)
            return None


monitoring_client = ChangeDetectionClient()
