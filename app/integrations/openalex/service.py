"""OpenAlex integration service.

Extracts research paper metadata from OpenAlex, reconstructs abstracts from inverted
indices, maps papers to ExternalRecord schemas, and ingests them into SQLite.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.integrations.openalex.client import OpenAlexClient, openalex_client
from app.schemas.external import ExternalRecord, IngestionResult
from app.utils.logging import get_logger

logger = get_logger("app.integrations.openalex.service")


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """Reconstruct plain-text abstract from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return None
    try:
        word_positions: List[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in word_positions)
    except Exception as exc:
        logger.debug("Failed to reconstruct abstract: %s", exc)
        return None


class OpenAlexService:
    """Service for searching and ingesting academic papers from OpenAlex."""

    def __init__(
        self,
        client: Optional[OpenAlexClient] = None,
        ingestion_pipeline: Optional[IngestionPipeline] = None,
    ) -> None:
        self.client = client or openalex_client
        self.pipeline = ingestion_pipeline or default_pipeline

    def map_work_to_record(self, item: Dict[str, Any]) -> ExternalRecord:
        """Map raw OpenAlex work item to ExternalRecord."""
        raw_id = item.get("id") or ""
        source_id = raw_id.split("/")[-1] if "/" in raw_id else raw_id

        # Authors
        authors = []
        for auth in (item.get("authorships") or []):
            if isinstance(auth, dict):
                name = (auth.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)

        primary_loc = item.get("primary_location") or {}
        source_info = primary_loc.get("source") or {}
        oa_info = item.get("open_access") or {}

        # URLs
        doi = item.get("doi")
        oa_url = oa_info.get("oa_url")
        landing_url = primary_loc.get("landing_page_url") or doi or raw_id
        canonical_url = oa_url or landing_url or doi or f"https://openalex.org/{source_id}"

        # Abstract
        abstract = reconstruct_abstract(item.get("abstract_inverted_index"))

        meta = {
            "doi": doi,
            "authors": authors,
            "publication_year": item.get("publication_year"),
            "cited_by_count": item.get("cited_by_count", 0),
            "is_oa": oa_info.get("is_oa", False),
            "oa_status": oa_info.get("oa_status"),
            "oa_url": oa_url,
            "venue": source_info.get("display_name"),
        }

        return ExternalRecord(
            source="openalex",
            source_id=source_id,
            record_type="research_paper",
            title=item.get("title") or f"Research Paper {source_id}",
            url=canonical_url,
            description=abstract,
            published_at=item.get("publication_date"),
            updated_at=item.get("updated_date"),
            metadata=meta,
        )

    async def search_and_ingest(
        self,
        query: str,
        per_page: int = 20,
        sort: str = "publication_date:desc",
        limit: Optional[int] = None,
    ) -> IngestionResult:
        """Search academic papers and ingest into SQLite."""
        effective_per_page = limit or per_page
        items = await self.client.search_works(query=query, per_page=effective_per_page, sort=sort)
        records = [self.map_work_to_record(item) for item in items if item.get("title")]
        return await self.pipeline.ingest_batch(records, source_name="openalex")

    async def fetch_recent_and_ingest(
        self,
        topic: Optional[str] = None,
        from_publication_date: Optional[str] = None,
        per_page: int = 20,
    ) -> IngestionResult:
        """Fetch recent publications by topic and ingest into SQLite."""
        items = await self.client.get_recent_papers(
            topic=topic,
            from_publication_date=from_publication_date,
            per_page=per_page,
        )
        records = [self.map_work_to_record(item) for item in items if item.get("title")]
        return await self.pipeline.ingest_batch(records, source_name="openalex")


openalex_service = OpenAlexService()
