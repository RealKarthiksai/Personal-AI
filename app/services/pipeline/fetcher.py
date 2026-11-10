"""Phase 2: Parallel search and page content fetcher."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
import httpx

from app.config import config
from app.services.extractor_service import ExtractorService
from app.services.search_service import SearchService
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.fetcher")

_search_service = SearchService()
_extractor_service = ExtractorService(max_content_chars=config.page_chars)


def is_safe_url(url: str) -> bool:
    """Validate URL syntax and block internal/localhost/private network targets."""
    if not _extractor_service.is_valid_url(url):
        return False
    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
            return False
        # Prevent SSRF on internal IP ranges if resolved
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                return False
        except ValueError:
            pass  # Normal domain name, allowed
        return True
    except Exception:
        return False


async def search_urls(query: str) -> List[Dict[str, str]]:
    """Query SearXNG via SearchService and return normalized items."""
    try:
        results = await _search_service.search(query=query, num_results=4, use_cache=True)
        return [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results if r.url]
    except Exception as exc:
        logger.warning("Search query failed for %r: %s", query, exc)
        return []


def _extract_with_trafilatura(html_text: str) -> str:
    """Synchronous CPU extraction via trafilatura."""
    try:
        import trafilatura
        return trafilatura.extract(html_text) or ""
    except Exception:
        return ""


async def _fetch(client: httpx.AsyncClient, item: Dict[str, str], sem: asyncio.Semaphore) -> Optional[Dict[str, str]]:
    url = item["url"]
    if not is_safe_url(url):
        return None

    max_chars = config.page_chars

    async with sem:
        text = ""
        try:
            # 1. Fast HTTP fetch with trafilatura in worker thread
            resp = await client.get(url, timeout=9.0, follow_redirects=True)
            if resp.status_code == 200:
                text = await asyncio.to_thread(_extract_with_trafilatura, resp.text)
        except Exception as e:
            logger.debug("Fast HTTP fetch failed for %s: %s; falling back to ExtractorService", url, e)

        # 2. Fall back to ExtractorService (supports cache & Crawl4AI)
        if not text:
            try:
                extracted = await _extractor_service.extract(url, use_cache=True)
                if extracted and extracted.success and extracted.markdown:
                    text = extracted.markdown
            except Exception as e:
                logger.debug("ExtractorService extraction failed for %s: %s", url, e)

        # 3. Last fallback: search snippet
        if not text:
            text = item.get("snippet", "")

    clean_text = text.strip()
    if clean_text:
        return {"url": url, "text": clean_text[:max_chars]}
    return None


async def gather(queries: List[str]) -> List[Dict[str, str]]:
    """Execute search queries concurrently, deduplicate by domain, and fetch content."""
    if not queries:
        return []

    results = await asyncio.gather(*(search_urls(q) for q in queries), return_exceptions=True)
    seen_domains: Set[str] = set()
    items: List[Dict[str, str]] = []

    for res in results:
        if isinstance(res, Exception) or not res:
            continue
        for it in res:
            try:
                domain = urlparse(it["url"]).netloc.lower()
            except Exception:
                continue
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                items.append(it)

    max_pages = config.max_pages
    items = items[:max_pages]

    sem = asyncio.Semaphore(5)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
        pages = await asyncio.gather(*(_fetch(client, it, sem) for it in items), return_exceptions=True)

    valid_pages = [p for p in pages if isinstance(p, dict) and p.get("text")]
    return valid_pages
