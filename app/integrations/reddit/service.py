"""Reddit integration service.

Normalizes Reddit posts into ExternalRecord schemas and persists them via the
Common Ingestion Pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.integrations.reddit.client import RedditClient, reddit_client
from app.schemas.external import ExternalRecord, IngestionResult
from app.utils.logging import get_logger

logger = get_logger("app.integrations.reddit.service")


class RedditService:
    """Service for retrieving and ingesting community discussions from Reddit."""

    def __init__(
        self,
        client: Optional[RedditClient] = None,
        ingestion_pipeline: Optional[IngestionPipeline] = None,
    ) -> None:
        self.client = client or reddit_client
        self.pipeline = ingestion_pipeline or default_pipeline

    def map_post_to_record(self, item: Dict[str, Any]) -> ExternalRecord:
        """Map raw Reddit post dict to ExternalRecord."""
        post_id = item.get("name") or f"t3_{item.get('id')}"
        permalink = item.get("permalink")
        url = f"https://reddit.com{permalink}" if permalink else item.get("url") or f"https://reddit.com/{post_id}"

        # Parse creation timestamp
        created_utc = item.get("created_utc")
        published_at = None
        if created_utc:
            try:
                published_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).isoformat()
            except Exception:
                published_at = None

        meta = {
            "subreddit": item.get("subreddit"),
            "author": item.get("author"),
            "score": item.get("score", 0),
            "comments": item.get("num_comments", 0),
            "num_comments": item.get("num_comments", 0),
            "upvote_ratio": item.get("upvote_ratio"),
            "link_flair_text": item.get("link_flair_text"),
            "is_self": item.get("is_self", True),
        }

        # Tags
        tags = []
        if item.get("subreddit"):
            tags.append(f"r/{item.get('subreddit')}")
        if item.get("link_flair_text"):
            tags.append(str(item.get("link_flair_text")))
        meta["tags"] = tags

        # Text content
        selftext = item.get("selftext") or ""

        return ExternalRecord(
            source="reddit",
            source_id=post_id,
            record_type="discussion",
            title=item.get("title") or "Reddit Discussion",
            url=url,
            description=selftext if selftext else None,
            published_at=published_at,
            metadata=meta,
        )

    async def fetch_subreddit_and_ingest(
        self,
        subreddit: str,
        listing: str = "hot",
        limit: int = 25,
    ) -> IngestionResult:
        """Fetch posts from a subreddit and ingest into SQLite."""
        items = await self.client.get_subreddit_posts(subreddit=subreddit, listing=listing, limit=limit)
        records = [self.map_post_to_record(item) for item in items if item.get("title")]
        return await self.pipeline.ingest_batch(records, source_name="reddit")

    # Alias for convenience
    fetch_and_ingest = fetch_subreddit_and_ingest

    async def search_and_ingest(
        self,
        query: str,
        subreddit: Optional[str] = None,
        sort: str = "relevance",
        limit: int = 25,
    ) -> IngestionResult:
        """Search posts on Reddit and ingest into SQLite."""
        items = await self.client.search_posts(query=query, subreddit=subreddit, sort=sort, limit=limit)
        records = [self.map_post_to_record(item) for item in items if item.get("title")]
        return await self.pipeline.ingest_batch(records, source_name="reddit")


reddit_service = RedditService()
