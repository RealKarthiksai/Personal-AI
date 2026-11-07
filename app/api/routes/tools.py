"""FastAPI routes for Web Search, Web Extraction, and tool metrics."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import repository
from app.services.extractor_service import extractor_service
from app.services.search_service import search_service
from app.utils.logging import get_logger

logger = get_logger("app.api.tools")

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query string")
    num_results: int = Field(default=5, ge=1, le=20)
    use_cache: bool = Field(default=True)


class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    engine: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    count: int
    results: List[SearchResultItem]


class ExtractRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Target webpage URL")
    use_cache: bool = Field(default=True)


class ExtractResponse(BaseModel):
    url: str
    title: str
    markdown: str
    success: bool
    error: Optional[str] = None


@router.post("/search", response_model=SearchResponse)
async def run_search(payload: SearchRequest) -> SearchResponse:
    """Execute a web search via SearXNG and return structured results."""
    try:
        results = await search_service.search(
            query=payload.query,
            num_results=payload.num_results,
            use_cache=payload.use_cache,
        )
        return SearchResponse(
            query=payload.query,
            count=len(results),
            results=[
                SearchResultItem(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    engine=r.engine,
                )
                for r in results
            ],
        )
    except Exception as exc:
        logger.error("API search failed for query %r: %s", payload.query, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/extract", response_model=ExtractResponse)
async def run_extract(payload: ExtractRequest) -> ExtractResponse:
    """Extract clean readable markdown from a webpage URL."""
    try:
        extracted = await extractor_service.extract(
            url=payload.url,
            use_cache=payload.use_cache,
        )
        return ExtractResponse(
            url=extracted.url,
            title=extracted.title,
            markdown=extracted.markdown,
            success=extracted.success,
            error=extracted.error,
        )
    except Exception as exc:
        logger.error("API extraction failed for url %r: %s", payload.url, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/status")
async def tools_status() -> dict:
    """Return runtime connectivity status for all active tools."""
    searx_ok = False
    searx_error = None
    try:
        import httpx
        from app.config import config

        if config.searxng_base_url:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{config.searxng_base_url}/healthz")
                searx_ok = resp.status_code == 200
    except Exception as exc:
        searx_error = str(exc)

    return {
        "searxng": {
            "configured": bool(config.searxng_base_url),
            "endpoint": config.searxng_base_url,
            "healthy": searx_ok,
            "error": searx_error,
        },
        "crawl4ai": {
            "status": "ready",
            "browser": "playwright-chromium",
        },
    }
