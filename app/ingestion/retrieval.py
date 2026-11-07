"""Context Manager retrieval bridge for stored external records.

Queries SQLite external_records across GitHub, Reddit, OpenAlex, RSS, and website
monitors, and formats structured facts for injection into local LLM inference context.
"""

from __future__ import annotations

from typing import List, Optional

from app.ingestion.storage import query_records
from app.schemas.external import ExternalRecord, ExternalRecordQuery
from app.utils.logging import get_logger

logger = get_logger("app.ingestion.retrieval")


def retrieve_external_information(
    query: Optional[str] = None,
    sources: Optional[List[str]] = None,
    record_types: Optional[List[str]] = None,
    limit: int = 5,
    since: Optional[str] = None,
) -> List[ExternalRecord]:
    """Retrieve relevant external records from SQLite for context injection."""
    params = ExternalRecordQuery(
        query=query,
        sources=sources,
        record_types=record_types,
        since=since,
        limit=limit,
    )
    records = query_records(params)
    logger.debug(
        "retrieve_external_information: query=%r | sources=%r | found=%d",
        query,
        sources,
        len(records),
    )
    return records


def format_records_for_llm(records: List[ExternalRecord]) -> str:
    """Format external records into concise markdown cards with links and dates."""
    if not records:
        return ""

    cards: List[str] = []
    cards.append("### Ingested External Records:")

    for idx, r in enumerate(records, start=1):
        lines: List[str] = []
        source_label = r.source.capitalize()
        type_label = r.record_type.replace("_", " ").title()

        lines.append(f"{idx}. [{r.title}]({r.url}) ({source_label} • {type_label})")
        if r.published_at:
            lines.append(f"   • Published: {r.published_at[:10]}")
        if r.description:
            clean_desc = r.description.replace("\n", " ").strip()
            if len(clean_desc) > 220:
                clean_desc = clean_desc[:220].rsplit(" ", 1)[0] + "..."
            lines.append(f"   • Summary: {clean_desc}")

        # Highlight important metadata attributes if present
        meta_items: List[str] = []
        if "stars" in r.metadata:
            meta_items.append(f"⭐ {r.metadata['stars']} stars")
        if "score" in r.metadata:
            meta_items.append(f"Upvotes: {r.metadata['score']}")
        if "comments" in r.metadata:
            meta_items.append(f"Comments: {r.metadata['comments']}")
        if "authors" in r.metadata and isinstance(r.metadata["authors"], list):
            auth_str = ", ".join(r.metadata["authors"][:3])
            meta_items.append(f"Authors: {auth_str}")
        if "doi" in r.metadata:
            meta_items.append(f"DOI: {r.metadata['doi']}")

        if meta_items:
            lines.append(f"   • Details: {' | '.join(meta_items)}")

        cards.append("\n".join(lines))

    return "\n\n".join(cards)
