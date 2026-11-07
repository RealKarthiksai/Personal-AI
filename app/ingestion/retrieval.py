"""Context Manager retrieval bridge and topical digest compiler for stored external records.

Queries SQLite external_records across GitHub, Reddit, OpenAlex, RSS, and website
monitors, applies log-scale ranking with source quotas, and formats structured facts
with manifest accounting for direct rendering.
"""

from __future__ import annotations

import html
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from app.database.database import transaction
from app.ingestion.storage import query_records
from app.schemas.external import ExternalRecord, ExternalRecordQuery
from app.schemas.manifest import (
    RetrievalManifest,
    SourceManifestEntry,
    SourceOrigin,
    SourceStatus,
)
from app.utils.logging import get_logger

logger = get_logger("app.ingestion.retrieval")

# Known topic mappings to typical sources
TOPIC_SOURCE_MAP = {
    "ai": ["github", "reddit", "openalex", "rss"],
    "machine learning": ["github", "reddit", "openalex", "rss"],
    "astronomy": ["openalex", "rss"],
    "space": ["openalex", "rss"],
    "finance": ["rss"],
    "economy": ["rss"],
    "climate": ["openalex", "rss"],
    "environment": ["openalex", "rss"],
    "quantum": ["openalex", "github", "rss"],
}


def get_start_of_day_utc(tz_name: str = "Asia/Kolkata") -> str:
    """Compute 00:00:00 today in the given user timezone, converted to UTC ISO format."""
    try:
        user_tz = ZoneInfo(tz_name)
    except Exception:
        user_tz = timezone.utc

    now_user = datetime.now(user_tz)
    midnight_user = datetime(now_user.year, now_user.month, now_user.day, 0, 0, 0, tzinfo=user_tz)
    midnight_utc = midnight_user.astimezone(timezone.utc)
    return midnight_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_delivered_record_ids(user_id: str, window_hours: int = 72) -> Set[int]:
    """Retrieve record IDs delivered to user in the given window to avoid repeating items."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT record_id FROM delivered_items
            WHERE user_id = ? AND delivered_at >= ?
            """,
            (user_id, cutoff),
        ).fetchall()
        return {r["record_id"] for r in rows}


def record_delivered_items(
    user_id: str,
    record_ids: List[int],
    channel: str = "telegram",
    kind: str = "briefing",
) -> None:
    """Record successfully delivered item IDs into delivered_items for deduplication."""
    if not record_ids:
        return
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        for rid in record_ids:
            try:
                conn.execute(
                    """
                    INSERT INTO delivered_items (user_id, record_id, channel, kind, delivered_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, rid, channel, kind, now_utc),
                )
            except Exception as e:
                logger.debug("Failed to record delivered item %s: %s", rid, e)


def compute_record_score(
    record: ExternalRecord,
    now: Optional[datetime] = None,
    user_interests: Optional[List[str]] = None,
) -> float:
    """Compute log-scale engagement score with recency weighting and interest personalization."""
    current_time = now or datetime.now(timezone.utc)
    base_score = 1.0

    meta = record.metadata or {}
    if "stars" in meta and isinstance(meta["stars"], (int, float)):
        base_score += math.log10(max(meta["stars"], 0) + 1.0) * 1.5

    if "score" in meta and isinstance(meta["score"], (int, float)):
        base_score += math.log10(max(meta["score"], 0) + 1.0) * 1.0

    if "cited_by_count" in meta and isinstance(meta["cited_by_count"], (int, float)):
        base_score += math.log10(max(meta["cited_by_count"], 0) + 1.0) * 1.2

    # Deterministic user interest personalization boost (0 LLM calls)
    if user_interests:
        full_text = f"{record.title} {record.description or ''}".lower()
        for interest in user_interests:
            clean_int = interest.strip().lower()
            if clean_int and clean_int in full_text:
                base_score += 1.5
                break

    # Recency decay
    rec_time_str = record.published_at or record.fetched_at
    if rec_time_str:
        try:
            # Parse ISO string
            clean_ts = rec_time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hours_old = max((current_time - dt).total_seconds() / 3600.0, 0.0)
            recency_weight = 1.0 / (1.0 + (hours_old / 48.0))
            base_score *= (0.5 + 0.5 * recency_weight)
        except Exception:
            pass

    return base_score


def rank_and_quota_records(
    records: List[ExternalRecord],
    max_per_source: int = 3,
    limit: int = 10,
    excluded_ids: Optional[Set[int]] = None,
    user_interests: Optional[List[str]] = None,
) -> List[ExternalRecord]:
    """Score, rank, and quota records so no single source crowds out others."""
    pool = [r for r in records if not (excluded_ids and r.id in excluded_ids)]
    if not pool:
        return []

    now = datetime.now(timezone.utc)
    scored = [(r, compute_record_score(r, now=now, user_interests=user_interests)) for r in pool]
    # Sort descending by score
    scored.sort(key=lambda x: x[1], reverse=True)

    results: List[ExternalRecord] = []
    source_counts: Dict[str, int] = {}

    for rec, _ in scored:
        src = rec.source.lower()
        if source_counts.get(src, 0) < max_per_source:
            results.append(rec)
            source_counts[src] = source_counts.get(src, 0) + 1
            if len(results) >= limit:
                break

    return results


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


def parse_digest_request(text: str) -> Tuple[Optional[int], List[str]]:
    """Extract requested count and topic list from a topical digest query."""
    clean = text.lower()

    # Requested count (e.g. "10 most important", "top 5")
    count_match = re.search(r"\b(\d+)\b", clean)
    requested_count = int(count_match.group(1)) if count_match else None
    if requested_count and (requested_count < 1 or requested_count > 25):
        requested_count = 10

    # Topic discovery
    detected_topics = []
    for topic_kw in TOPIC_SOURCE_MAP.keys():
        if re.search(r"\b" + re.escape(topic_kw) + r"\b", clean):
            detected_topics.append(topic_kw)

    return requested_count, detected_topics


def format_records_for_llm(records: List[ExternalRecord]) -> str:
    """Format external records into concise markdown cards with HTML-escaped titles."""
    if not records:
        return ""

    cards: List[str] = []
    for idx, r in enumerate(records, start=1):
        lines: List[str] = []
        source_label = r.source.capitalize()
        type_label = r.record_type.replace("_", " ").title()

        safe_title = html.escape(r.title).replace("[", "&#91;").replace("]", "&#93;")
        lines.append(f"<b>{idx}. <a href=\"{r.url}\">{safe_title}</a></b> ({source_label} • {type_label})")

        pub_date = r.published_at[:10] if r.published_at else "date unknown"
        lines.append(f"   • Published: {pub_date}")

        if r.description:
            clean_desc = html.escape(r.description.replace("\n", " ").strip())
            if len(clean_desc) > 220:
                clean_desc = clean_desc[:220].rsplit(" ", 1)[0] + "..."
            lines.append(f"   • Summary: {clean_desc}")

        # Structured metadata highlights
        meta_items: List[str] = []
        if "stars" in r.metadata:
            meta_items.append(f"⭐ {r.metadata['stars']} stars")
        if "score" in r.metadata:
            meta_items.append(f"Upvotes: {r.metadata['score']}")
        if "comments" in r.metadata:
            meta_items.append(f"Comments: {r.metadata['comments']}")
        if "authors" in r.metadata and isinstance(r.metadata["authors"], list):
            auth_str = html.escape(", ".join(r.metadata["authors"][:3]))
            meta_items.append(f"Authors: {auth_str}")
        if "doi" in r.metadata:
            meta_items.append(f"DOI: {r.metadata['doi']}")

        if meta_items:
            lines.append(f"   • Details: {' | '.join(meta_items)}")

        cards.append("\n".join(lines))

    return "\n\n".join(cards)
