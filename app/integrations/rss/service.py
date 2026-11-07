"""RSS Integration Service.

Manages feed subscriptions in SQLite, maps RSS/Atom entries to ExternalRecord schemas,
and ingests articles via the Common Ingestion Pipeline.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database.database import transaction
from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.integrations.rss.client import RSSClient, rss_client, strip_html_tags
from app.schemas.external import ExternalRecord, IngestionResult
from app.utils.logging import get_logger

logger = get_logger("app.integrations.rss.service")


def struct_time_to_iso(st: Optional[time.struct_time]) -> Optional[str]:
    """Convert a time.struct_time from feedparser to an ISO-8601 string."""
    if not st:
        return None
    try:
        dt = datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


class RSSService:
    """Service for managing RSS/Atom feed subscriptions and ingestion."""

    def __init__(
        self,
        client: Optional[RSSClient] = None,
        ingestion_pipeline: Optional[IngestionPipeline] = None,
    ) -> None:
        self.client = client or rss_client
        self.pipeline = ingestion_pipeline or default_pipeline

    # --------------------------------------------------------------------------
    # Subscription Management
    # --------------------------------------------------------------------------

    def subscribe_feed(
        self,
        url: str,
        title: Optional[str] = None,
        category: Optional[str] = "general",
    ) -> Dict[str, Any]:
        """Subscribe to a new RSS/Atom feed."""
        resolved = self.client.resolve_feed_url(url)
        with transaction() as conn:
            existing = conn.execute(
                "SELECT id, url, title, category, enabled FROM feed_subscriptions WHERE url = ?",
                (resolved,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE feed_subscriptions SET enabled = 1, title = COALESCE(?, title), category = COALESCE(?, category) WHERE id = ?",
                    (title, category, existing["id"]),
                )
                feed_id = existing["id"]
                created = False
            else:
                cur = conn.execute(
                    "INSERT INTO feed_subscriptions (url, title, category, enabled) VALUES (?, ?, ?, 1)",
                    (resolved, title or resolved, category),
                )
                feed_id = cur.lastrowid
                created = True

        return {
            "id": feed_id,
            "url": resolved,
            "title": title or resolved,
            "category": category,
            "enabled": True,
            "created": created,
        }

    def unsubscribe_feed(self, feed_id_or_url: str) -> bool:
        """Unsubscribe (disable) a feed subscription."""
        with transaction() as conn:
            if feed_id_or_url.isdigit():
                cur = conn.execute(
                    "UPDATE feed_subscriptions SET enabled = 0 WHERE id = ?",
                    (int(feed_id_or_url),),
                )
            else:
                cur = conn.execute(
                    "UPDATE feed_subscriptions SET enabled = 0 WHERE url = ?",
                    (feed_id_or_url,),
                )
            return cur.rowcount > 0

    def list_subscriptions(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """List current feed subscriptions."""
        query = "SELECT id, url, title, category, enabled, last_fetched_at, created_at FROM feed_subscriptions"
        params: List[Any] = []
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY id ASC"

        with transaction() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def update_last_fetched(self, url: str) -> None:
        """Update last_fetched_at timestamp for a feed."""
        now = datetime.now(timezone.utc).isoformat()
        with transaction() as conn:
            conn.execute(
                "UPDATE feed_subscriptions SET last_fetched_at = ? WHERE url = ?",
                (now, url),
            )

    # --------------------------------------------------------------------------
    # Record Mapping
    # --------------------------------------------------------------------------

    def map_entry_to_record(
        self,
        feed_url: str,
        feed_title: str,
        entry: Dict[str, Any],
        feed_category: Optional[str] = None,
    ) -> ExternalRecord:
        """Map raw feedparser entry dict to ExternalRecord."""
        raw_id = entry.get("id") or entry.get("guid") or entry.get("link") or ""
        url = entry.get("link") or raw_id
        title = strip_html_tags(entry.get("title")) or "Untitled Article"

        # Content / Summary extraction
        content_val = None
        if "content" in entry and isinstance(entry["content"], list) and len(entry["content"]) > 0:
            content_val = entry["content"][0].get("value")
        raw_desc = content_val or entry.get("summary") or entry.get("description")
        description = strip_html_tags(raw_desc)

        # Dates
        pub_iso = struct_time_to_iso(entry.get("published_parsed")) or entry.get("published")
        updated_iso = struct_time_to_iso(entry.get("updated_parsed")) or entry.get("updated")

        # Tags / Categories
        tags = []
        if feed_category:
            tags.append(feed_category)
        for t in entry.get("tags", []):
            term = t.get("term") if isinstance(t, dict) else str(t)
            if term and term not in tags:
                tags.append(term)

        meta = {
            "feed_url": feed_url,
            "feed_title": feed_title,
            "author": entry.get("author"),
            "category": feed_category,
            "tags": tags,
            "comments_url": entry.get("comments"),
        }

        return ExternalRecord(
            source="rss",
            source_id=f"{feed_url}#{raw_id}",
            record_type="article",
            title=title,
            url=url,
            description=description,
            published_at=pub_iso,
            updated_at=updated_iso,
            metadata=meta,
        )

    # --------------------------------------------------------------------------
    # Ingestion & Sync
    # --------------------------------------------------------------------------

    async def sync_feed(self, url: str, category: Optional[str] = None) -> IngestionResult:
        """Fetch an individual feed, parse its entries, and ingest into SQLite."""
        resolved = self.client.resolve_feed_url(url)
        parsed = await self.client.fetch_feed(resolved)
        feed_header = parsed.get("feed", {})
        feed_title = feed_header.get("title") or resolved

        entries = parsed.get("entries", [])
        if not entries:
            self.update_last_fetched(resolved)
            return IngestionResult(total_received=0)

        records: List[ExternalRecord] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            record = self.map_entry_to_record(resolved, feed_title, e, feed_category=category)
            if record.url and record.title:
                records.append(record)

        result = await self.pipeline.ingest_batch(records, source_name="rss")
        self.update_last_fetched(resolved)
        return result

    async def sync_all_subscriptions(self) -> Dict[str, Any]:
        """Fetch and ingest all active feed subscriptions."""
        subs = self.list_subscriptions(enabled_only=True)
        results: Dict[str, Any] = {}
        total_inserted = 0
        total_updated = 0

        for sub in subs:
            url = sub["url"]
            category = sub.get("category")
            try:
                res = await self.sync_feed(url, category=category)
                results[url] = res.model_dump()
                total_inserted += res.inserted
                total_updated += res.updated
            except Exception as exc:
                logger.error("Error syncing feed %s: %s", url, exc)
                results[url] = {"error": str(exc), "inserted": 0, "updated": 0}

        return {
            "feeds_synced": len(subs),
            "total_inserted": total_inserted,
            "total_updated": total_updated,
            "details": results,
        }


rss_service = RSSService()
