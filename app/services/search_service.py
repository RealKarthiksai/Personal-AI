"""Web search service integrating local SearXNG metasearch with SQLite caching.

Queries local SearXNG (Google, DuckDuckGo, Bing, Brave, Wikipedia) and returns
clean, structured search results for the local LLM.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import List, Optional

import httpx

from app.config import config
from app.database import repository
from app.database.models import SearchResult
from app.utils.logging import get_logger

logger = get_logger("app.search_service")


class SearchServiceError(Exception):
    """Base exception for search service errors."""


class SearchService:
    """Service client for local SearXNG metasearch."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        cache_ttl_seconds: Optional[int] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or config.searxng_base_url).rstrip("/")
        self.cache_ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else config.search_cache_ttl_seconds
        )
        self.timeout = timeout_seconds

    @staticmethod
    def _hash_query(query: str) -> str:
        normalized = " ".join(query.strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def search(
        self,
        query: str,
        num_results: int = 5,
        use_cache: bool = True,
    ) -> List[SearchResult]:
        """Execute a web search across configured engines via SearXNG.

        Checks SQLite search_cache first. On cache miss, queries SearXNG,
        persists to cache, and returns top `num_results` entries.
        """
        start_time = time.monotonic()
        clean_query = query.strip()
        if not clean_query:
            return []

        query_hash = self._hash_query(clean_query)

        # 1. Check cache
        if use_cache:
            cached_json = repository.get_cached_search(
                query_hash=query_hash,
                max_age_seconds=self.cache_ttl,
            )
            if cached_json:
                try:
                    data = json.loads(cached_json)
                    results = [SearchResult(**item) for item in data[:num_results]]
                    logger.info("Search cache hit | query=%r | results=%d", clean_query, len(results))
                    return results
                except Exception as exc:
                    logger.warning("Failed to deserialize cached search: %s", exc)

        # 2. Query SearXNG
        if not self.base_url:
            raise SearchServiceError("SEARXNG_BASE_URL is not configured")

        url = f"{self.base_url}/search"
        params = {
            "q": clean_query,
            "format": "json",
            "categories": "general",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
        except httpx.RequestError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            repository.log_tool_execution(
                tool_name="searxng_search",
                input_data=clean_query,
                output_summary=f"ERROR: {exc}",
                duration_ms=duration_ms,
            )
            raise SearchServiceError(f"Cannot reach SearXNG at {url}: {exc}") from exc

        if resp.status_code >= 400:
            duration_ms = (time.monotonic() - start_time) * 1000
            repository.log_tool_execution(
                tool_name="searxng_search",
                input_data=clean_query,
                output_summary=f"HTTP {resp.status_code}",
                duration_ms=duration_ms,
            )
            raise SearchServiceError(f"SearXNG returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise SearchServiceError(f"SearXNG returned invalid JSON: {exc}") from exc

        raw_results = payload.get("results") or []
        parsed_results: List[SearchResult] = []

        for item in raw_results:
            title = str(item.get("title") or "").strip()
            item_url = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or "").strip()
            engine = str(item.get("engine") or "")
            if item_url and (title or snippet):
                parsed_results.append(
                    SearchResult(
                        title=title,
                        url=item_url,
                        snippet=snippet,
                        engine=engine,
                    )
                )

        # 3. Cache results
        if parsed_results:
            serialized = json.dumps(
                [
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                        "engine": r.engine,
                    }
                    for r in parsed_results
                ]
            )
            repository.set_cached_search(
                query_hash=query_hash,
                query=clean_query,
                results_json=serialized,
            )

        duration_ms = (time.monotonic() - start_time) * 1000
        repository.log_tool_execution(
            tool_name="searxng_search",
            input_data=clean_query,
            output_summary=f"Found {len(parsed_results)} results",
            duration_ms=duration_ms,
        )

        return parsed_results[:num_results]

    def format_for_llm(self, results: List[SearchResult], max_items: int = 3) -> str:
        """Format search results into a clean, concise markdown block for the LLM."""
        if not results:
            return "No web search results found."

        lines: List[str] = ["Web Search Results:"]
        for idx, res in enumerate(results[:max_items], 1):
            snippet = res.snippet.strip()
            if len(snippet) > 180:
                snippet = snippet[:180] + "..."
            lines.append(f"{idx}. [{res.title}]({res.url}): {snippet}")
        return "\n".join(lines)


search_service = SearchService()
