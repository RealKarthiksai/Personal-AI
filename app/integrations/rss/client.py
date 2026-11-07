"""RSS and Atom feed client using feedparser and HTTPX.

Supports standard RSS/Atom feeds, podcast feeds, and RSSHub dynamic routes.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
import feedparser
import httpx

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.integrations.rss.client")

# Clean HTML tags from summary/title
HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html_tags(text: Optional[str]) -> Optional[str]:
    """Strip basic HTML tags and normalize spacing."""
    if not text:
        return None
    clean = HTML_TAG_RE.sub(" ", text)
    return " ".join(clean.split()).strip() or None


class RSSClient:
    """Asynchronous client for fetching and parsing RSS/Atom feeds."""

    def __init__(
        self,
        rsshub_base: Optional[str] = None,
        timeout_seconds: float = 15.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self.rsshub_base = (rsshub_base or config.rsshub_base_url or "https://rsshub.app").rstrip("/")
        self.timeout = timeout_seconds
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; KarnaFeedReader/1.0; +https://github.com/vhanghar/karna)"

    def resolve_feed_url(self, url: str) -> str:
        """Resolve custom RSSHub scheme or shorthand path into a full HTTP URL."""
        url = url.strip()
        if url.startswith("rsshub://"):
            route = url[len("rsshub://") :].lstrip("/")
            return f"{self.rsshub_base}/{route}"
        if url.startswith("/") and not url.startswith("//"):
            return f"{self.rsshub_base}{url}"
        return url

    async def fetch_feed(self, url: str) -> Dict[str, Any]:
        """Fetch feed from network asynchronously and parse with feedparser."""
        resolved_url = self.resolve_feed_url(url)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(resolved_url, headers=headers)
                response.raise_for_status()
                xml_content = response.text
        except Exception as exc:
            logger.warning("Failed to fetch RSS feed %s: %s", resolved_url, exc)
            return {"feed": {}, "entries": [], "bozo": True, "error": str(exc)}

        # feedparser.parse is CPU-bound and performs blocking parsing; execute in thread pool
        parsed = await asyncio.to_thread(feedparser.parse, xml_content)
        return parsed

    def parse_raw_xml(self, xml_content: str) -> Dict[str, Any]:
        """Parse raw XML string into feed structure."""
        return feedparser.parse(xml_content)


rss_client = RSSClient()
