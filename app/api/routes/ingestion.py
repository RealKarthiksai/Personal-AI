"""FastAPI router for external record ingestion and retrieval."""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Query

from app.ingestion.pipeline import pipeline
from app.ingestion.storage import list_sources, query_records
from app.schemas.external import ExternalRecord, ExternalRecordQuery, IngestionResult

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])


@router.post("/ingest", response_model=IngestionResult)
async def ingest_records(records: List[ExternalRecord]) -> IngestionResult:
    """Ingest a batch of external records into the common SQLite repository."""
    return await pipeline.ingest_batch(records)


@router.get("/records", response_model=List[ExternalRecord])
async def get_records(
    q: Optional[str] = Query(default=None, description="Search query against title and description"),
    source: Optional[str] = Query(default=None, description="Filter by source name"),
    record_type: Optional[str] = Query(default=None, description="Filter by record type"),
    since: Optional[str] = Query(default=None, description="ISO-8601 date cutoff"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> List[ExternalRecord]:
    """Query ingested external records."""
    sources = [s.strip().lower() for s in source.split(",")] if source else None
    types = [t.strip().lower() for t in record_type.split(",")] if record_type else None
    params = ExternalRecordQuery(
        query=q,
        sources=sources,
        record_types=types,
        since=since,
        limit=limit,
        offset=offset,
    )
    return query_records(params)


@router.get("/records/sources")
async def get_registered_sources() -> List[dict]:
    """List registered external source providers and stored record metrics."""
    return list_sources()
