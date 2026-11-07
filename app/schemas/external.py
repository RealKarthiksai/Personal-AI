"""Pydantic schemas for the Common Ingestion Pipeline across external sources.

Supports uniform representation for GitHub repositories, Reddit discussions,
OpenAlex research papers, RSS articles, and website change alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExternalRecord(BaseModel):
    """Unified data model for records ingested from external sources."""

    source: str = Field(
        ...,
        description="Provider source identifier (e.g. 'github', 'reddit', 'openalex', 'rss', 'changedetection')",
    )
    source_id: str = Field(
        ...,
        description="Unique identifier within the provider (e.g. repo 'owner/name', Reddit post ID, DOI, or GUID)",
    )
    record_type: str = Field(
        ...,
        description="Type of entity: 'repository', 'discussion', 'research_paper', 'article', 'change_alert'",
    )
    title: str = Field(..., description="Primary title or heading")
    url: str = Field(..., description="Canonical target URL or permalink")
    description: Optional[str] = Field(default=None, description="Summary, abstract, or text content")
    published_at: Optional[str] = Field(default=None, description="ISO-8601 published date")
    updated_at: Optional[str] = Field(default=None, description="ISO-8601 updated date")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary provider-specific structured metadata (e.g. stars, authors, score, tags)",
    )
    fetched_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp when this record was fetched",
    )


class IngestionResult(BaseModel):
    """Summary of batch ingestion run."""

    total_received: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_identical: int = 0
    failed: int = 0
    errors: List[str] = Field(default_factory=list)


class ExternalRecordQuery(BaseModel):
    """Query parameters for searching and filtering external records."""

    query: Optional[str] = Field(default=None, description="Keyword search against title and description")
    sources: Optional[List[str]] = Field(default=None, description="Filter by sources (e.g. ['github', 'openalex'])")
    record_types: Optional[List[str]] = Field(default=None, description="Filter by types (e.g. ['repository'])")
    since: Optional[str] = Field(default=None, description="ISO-8601 date cutoff for published_at or fetched_at")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
