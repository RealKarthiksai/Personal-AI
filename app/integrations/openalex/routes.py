"""FastAPI router for OpenAlex academic literature integration."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Query

from app.integrations.openalex.client import openalex_client
from app.integrations.openalex.service import openalex_service

router = APIRouter(prefix="/api/integrations/openalex", tags=["OpenAlex Integration"])


@router.get("/search")
async def search_works(
    q: Optional[str] = Query(default=None, description="Academic search query (e.g. 'local llm agents')"),
    query: Optional[str] = Query(default=None, description="Academic search query alias"),
    sort: str = Query(default="publication_date:desc", description="Sort order (e.g. 'publication_date:desc', 'cited_by_count:desc')"),
    per_page: int = Query(default=20, ge=1, le=50),
    limit: Optional[int] = Query(default=None, ge=1, le=50),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Search academic papers on OpenAlex."""
    effective_query = q or query or ""
    effective_per_page = limit or per_page
    items = await openalex_client.search_works(query=effective_query, per_page=effective_per_page, sort=sort)
    ingestion_summary = None
    if ingest and items:
        records = [openalex_service.map_work_to_record(item) for item in items if item.get("title")]
        ingestion_summary = await openalex_service.pipeline.ingest_batch(records, source_name="openalex")

    ingestion_dump = ingestion_summary.model_dump() if ingestion_summary else None
    return {
        "count": len(items),
        "results": items,
        "ingested": ingestion_dump,
        "ingestion": ingestion_dump,
    }


@router.get("/recent")
async def get_recent_papers(
    topic: Optional[str] = Query(default=None, description="Topic to filter (e.g. 'reinforcement learning')"),
    from_date: Optional[str] = Query(default=None, description="ISO-8601 publication start date (YYYY-MM-DD)"),
    per_page: int = Query(default=20, ge=1, le=50),
    ingest: bool = Query(default=True, description="Automatically ingest results into SQLite"),
) -> Dict[str, Any]:
    """Fetch recent publications from OpenAlex."""
    items = await openalex_client.get_recent_papers(topic=topic, from_publication_date=from_date, per_page=per_page)
    ingestion_summary = None
    if ingest and items:
        records = [openalex_service.map_work_to_record(item) for item in items if item.get("title")]
        ingestion_summary = await openalex_service.pipeline.ingest_batch(records, source_name="openalex")

    return {
        "count": len(items),
        "results": items,
        "ingested": ingestion_summary.model_dump() if ingestion_summary else None,
    }


@router.get("/authors")
async def search_authors(
    q: str = Query(..., description="Author name to search"),
    per_page: int = Query(default=10, ge=1, le=20),
) -> Dict[str, Any]:
    """Search researchers on OpenAlex."""
    items = await openalex_client.search_authors(query=q, per_page=per_page)
    return {
        "count": len(items),
        "results": items,
    }
