"""Web extraction service using Crawl4AI with fast HTTP fallback and SQLite caching.

Extracts readable markdown from webpages for LLM ingestion, trimming boilerplate
and caching pages by URL.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import config
from app.database import repository
from app.database.models import ExtractedContent
from app.utils.logging import get_logger

# Suppress Crawl4AI cloud banner
os.environ["CRAWL4AI_NO_CLOUD_NOTICE"] = "1"

logger = get_logger("app.extractor_service")


class ExtractorServiceError(Exception):
    """Base exception for web extractor errors."""


class ExtractorService:
    """Extracts clean markdown content from URLs."""

    def __init__(
        self,
        max_content_chars: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self.max_chars = (
            max_content_chars
            if max_content_chars is not None
            else config.crawler_max_content_chars
        )
        self.timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else config.crawler_timeout_seconds
        )

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Validate if string is a plausible HTTP(S) URL."""
        try:
            parsed = urlparse(url.strip())
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    async def _extract_fast_http(self, url: str) -> ExtractedContent:
        """Lightweight HTTP extraction for static content without headless browser."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            raise ExtractorServiceError(f"HTTP {resp.status_code} fetching {url}")

        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script, style, nav, footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else url

        # Extract text paragraphs and headers
        text_parts = []
        for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            txt = elem.get_text(separator=" ", strip=True)
            if txt and len(txt) > 20:
                text_parts.append(txt)

        text = "\n\n".join(text_parts)
        if not text:
            text = soup.get_text(separator="\n", strip=True)

        return ExtractedContent(
            url=url,
            title=title,
            markdown=text[: self.max_chars],
            success=True,
        )

    async def _extract_crawl4ai(self, url: str) -> ExtractedContent:
        """Full dynamic extraction using Crawl4AI (AsyncWebCrawler)."""
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            if not result.success:
                raise ExtractorServiceError(
                    result.error_message or f"Crawl4AI failed to extract {url}"
                )

            title = (
                result.metadata.get("title")
                if result.metadata and isinstance(result.metadata, dict)
                else url
            )
            markdown = result.markdown or ""

            # Trim to max chars
            if len(markdown) > self.max_chars:
                markdown = markdown[: self.max_chars] + "\n\n...[content truncated]"

            return ExtractedContent(
                url=url,
                title=title or url,
                markdown=markdown,
                success=True,
            )

    async def extract(self, url: str, use_cache: bool = True) -> ExtractedContent:
        """Extract web content from the given URL.

        Checks SQLite cache first. Attempts Crawl4AI extraction, falling back to
        fast HTTP extraction on failure.
        """
        start_time = time.monotonic()
        clean_url = url.strip()
        if not self.is_valid_url(clean_url):
            return ExtractedContent(
                url=clean_url,
                title="Invalid URL",
                markdown="",
                success=False,
                error="Invalid HTTP/HTTPS URL",
            )

        url_hash = self._hash_url(clean_url)

        # 1. Check SQLite page cache (default 24h)
        if use_cache:
            cached = repository.get_cached_page(url_hash=url_hash, max_age_seconds=86400)
            if cached:
                logger.info("Page cache hit | url=%r", clean_url)
                return ExtractedContent(
                    url=cached["url"],
                    title=cached["title"] or clean_url,
                    markdown=cached["markdown_content"],
                    success=True,
                )

        # 2. Extract via Crawl4AI (with fallback)
        extracted: Optional[ExtractedContent] = None
        error_msg: Optional[str] = None

        try:
            extracted = await self._extract_crawl4ai(clean_url)
        except Exception as exc:
            logger.warning("Crawl4AI failed for %s (%s); trying HTTP fallback", clean_url, exc)
            try:
                extracted = await self._extract_fast_http(clean_url)
            except Exception as http_exc:
                error_msg = f"Extraction failed: {exc} | Fallback failed: {http_exc}"
                logger.error("All extraction methods failed for %s: %s", clean_url, error_msg)

        duration_ms = (time.monotonic() - start_time) * 1000

        if extracted and extracted.success:
            # Cache extracted content
            repository.set_cached_page(
                url_hash=url_hash,
                url=clean_url,
                title=extracted.title,
                markdown_content=extracted.markdown,
            )
            repository.log_tool_execution(
                tool_name="web_extractor",
                input_data=clean_url,
                output_summary=f"Extracted {len(extracted.markdown)} chars",
                duration_ms=duration_ms,
            )
            return extracted

        # If both failed:
        repository.log_tool_execution(
            tool_name="web_extractor",
            input_data=clean_url,
            output_summary=f"ERROR: {error_msg}",
            duration_ms=duration_ms,
        )
        return ExtractedContent(
            url=clean_url,
            title="Extraction Failed",
            markdown="",
            success=False,
            error=error_msg or "Unknown extraction failure",
        )

    def format_for_llm(self, content: ExtractedContent) -> str:
        """Format extracted content into markdown for LLM consumption."""
        if not content.success or not content.markdown:
            return f"Failed to extract content from {content.url}: {content.error or 'No readable content'}"
        return (
            f"### Web Page Content from [{content.title}]({content.url}):\n\n"
            f"{content.markdown}"
        )


extractor_service = ExtractorService()
