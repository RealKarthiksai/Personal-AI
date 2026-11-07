"""FastAPI router for Reddit community discussions integration."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Query

from app.integrations.reddit.client import reddit_client
from app.integrations.reddit.service import reddit_service

router = APIRouter(prefix="/api/integrations/reddit", tags=["Reddit Integration"])


@router.get("/posts")
async def get_subreddit_posts(
    subreddit: str = Query(default="LocalLLaMA", description="Subreddit name (e.g. 'LocalLLaMA', 'MachineLearning')"),
    listing: str = Query(default="hot", description="Listing category: 'hot', 'new', 'top'"),
    limit: int = Query(default=25, ge=1, le=100),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Retrieve posts from a subreddit."""
    items = await reddit_client.get_subreddit_posts(subreddit=subreddit, listing=listing, limit=limit)
    ingestion_summary = None
    if ingest and items:
        records = [reddit_service.map_post_to_record(item) for item in items if item.get("title")]
        ingestion_summary = await reddit_service.pipeline.ingest_batch(records, source_name="reddit")

    ingestion_dump = ingestion_summary.model_dump() if ingestion_summary else None
    return {
        "subreddit": subreddit,
        "listing": listing,
        "count": len(items),
        "posts": items,
        "ingested": ingestion_dump,
        "ingestion": ingestion_dump,
    }


@router.get("/search")
async def search_posts(
    q: Optional[str] = Query(default=None, description="Search query string"),
    query: Optional[str] = Query(default=None, description="Search query string alias"),
    subreddit: Optional[str] = Query(default=None, description="Optional subreddit filter"),
    sort: str = Query(default="relevance", description="Sort by: 'relevance', 'hot', 'top', 'new'"),
    limit: int = Query(default=25, ge=1, le=100),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Search posts on Reddit."""
    effective_query = q or query or ""
    items = await reddit_client.search_posts(query=effective_query, subreddit=subreddit, sort=sort, limit=limit)
    ingestion_summary = None
    if ingest and items:
        records = [reddit_service.map_post_to_record(item) for item in items if item.get("title")]
        ingestion_summary = await reddit_service.pipeline.ingest_batch(records, source_name="reddit")

    ingestion_dump = ingestion_summary.model_dump() if ingestion_summary else None
    return {
        "query": effective_query,
        "subreddit": subreddit,
        "count": len(items),
        "posts": items,
        "ingested": ingestion_dump,
        "ingestion": ingestion_dump,
    }
