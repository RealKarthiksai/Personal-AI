"""FastAPI router for GitHub integration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

from app.integrations.github.client import github_client
from app.integrations.github.service import github_service
from app.schemas.external import IngestionResult

router = APIRouter(prefix="/api/integrations/github", tags=["GitHub Integration"])


@router.get("/search")
async def search_repositories(
    q: Optional[str] = Query(default=None, description="Search query string"),
    query: Optional[str] = Query(default=None, description="Search query string alias"),
    sort: str = Query(default="updated", description="Sort by: 'updated', 'stars', 'forks'"),
    order: str = Query(default="desc", description="Sort order: 'desc' or 'asc'"),
    per_page: int = Query(default=20, ge=1, le=100),
    limit: Optional[int] = Query(default=None, ge=1, le=100),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Search repositories via GitHub API."""
    effective_query = q or query or ""
    effective_per_page = limit or per_page
    items = await github_client.search_repositories(query=effective_query, sort=sort, order=order, per_page=effective_per_page)
    ingestion_summary = None
    if ingest and items:
        records = [github_service.map_repository_to_record(item) for item in items if item.get("html_url")]
        ingestion_summary = await github_service.pipeline.ingest_batch(records, source_name="github")

    ingestion_dump = ingestion_summary.model_dump() if ingestion_summary else None
    return {
        "count": len(items),
        "items": items,
        "ingested": ingestion_dump,
        "ingestion": ingestion_dump,
    }


@router.get("/trending")
async def get_trending_repositories(
    language: Optional[str] = Query(default=None, description="Filter by programming language"),
    topic: Optional[str] = Query(default=None, description="Filter by topic (e.g. 'llm', 'rag')"),
    since_days: int = Query(default=7, ge=1, le=30),
    min_stars: int = Query(default=50, ge=0),
    per_page: int = Query(default=20, ge=1, le=100),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Discover active / trending repositories based on recent pushes and star thresholds."""
    items = await github_client.get_trending(
        language=language,
        topic=topic,
        since_days=since_days,
        min_stars=min_stars,
        per_page=per_page,
    )
    ingestion_summary = None
    if ingest and items:
        records = [github_service.map_repository_to_record(item) for item in items if item.get("html_url")]
        ingestion_summary = await github_service.pipeline.ingest_batch(records, source_name="github")

    return {
        "count": len(items),
        "items": items,
        "ingested": ingestion_summary.model_dump() if ingestion_summary else None,
    }


@router.get("/releases")
async def get_releases(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    per_page: int = Query(default=10, ge=1, le=50),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Fetch releases for a given repository."""
    items = await github_client.get_releases(owner=owner, repo=repo, per_page=per_page)
    ingestion_summary = None
    if ingest and items:
        records = [github_service.map_release_to_record(owner, repo, item) for item in items if item.get("html_url")]
        ingestion_summary = await github_service.pipeline.ingest_batch(records, source_name="github")

    return {
        "repo": f"{owner}/{repo}",
        "count": len(items),
        "releases": items,
        "ingested": ingestion_summary.model_dump() if ingestion_summary else None,
    }


@router.get("/issues")
async def get_issues(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    state: str = Query(default="open", description="Issue state: 'open', 'closed', 'all'"),
    per_page: int = Query(default=10, ge=1, le=50),
) -> Dict[str, Any]:
    """Fetch issues for a given repository."""
    items = await github_client.get_issues(owner=owner, repo=repo, state=state, per_page=per_page)
    return {
        "repo": f"{owner}/{repo}",
        "count": len(items),
        "issues": items,
    }
