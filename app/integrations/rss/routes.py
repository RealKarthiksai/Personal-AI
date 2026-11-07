"""FastAPI router for RSS/Atom and RSSHub feeds integration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.integrations.rss.client import rss_client
from app.integrations.rss.service import rss_service

router = APIRouter(prefix="/api/integrations/rss", tags=["RSS Feeds Integration"])


class SubscribeRequest(BaseModel):
    url: str = Field(..., description="RSS/Atom feed URL or RSSHub path (e.g. 'https://hnrss.org/frontpage' or 'rsshub://github/repos/new')")
    title: Optional[str] = Field(default=None, description="Friendly title for this feed")
    category: Optional[str] = Field(default="general", description="Category tag (e.g. 'ai', 'tech', 'news')")


class SyncRequest(BaseModel):
    url: Optional[str] = Field(default=None, description="Specific feed URL to sync. If omitted, all subscriptions are synced.")


@router.get("/subscriptions")
async def get_subscriptions(
    enabled_only: bool = Query(default=True, description="Filter only enabled feeds"),
) -> List[Dict[str, Any]]:
    """List feed subscriptions."""
    return rss_service.list_subscriptions(enabled_only=enabled_only)


@router.post("/subscribe")
async def subscribe_feed(payload: SubscribeRequest) -> Dict[str, Any]:
    """Subscribe to an RSS/Atom feed."""
    return rss_service.subscribe_feed(
        url=payload.url,
        title=payload.title,
        category=payload.category,
    )


@router.delete("/subscriptions")
async def unsubscribe_feed(
    feed_id_or_url: str = Query(..., description="Feed ID or URL to unsubscribe"),
) -> Dict[str, Any]:
    """Unsubscribe / disable a feed."""
    success = rss_service.unsubscribe_feed(feed_id_or_url)
    if not success:
        raise HTTPException(status_code=404, detail="Feed subscription not found")
    return {"status": "unsubscribed", "target": feed_id_or_url}


@router.post("/sync")
async def sync_feeds(payload: Optional[SyncRequest] = None) -> Dict[str, Any]:
    """Sync one or all RSS subscriptions into SQLite."""
    target_url = payload.url if payload else None
    if target_url:
        result = await rss_service.sync_feed(target_url)
        return {
            "url": target_url,
            "result": result.model_dump(),
        }
    return await rss_service.sync_all_subscriptions()


@router.get("/preview")
async def preview_feed(
    url: str = Query(..., description="Feed URL or RSSHub path to preview"),
    limit: int = Query(default=10, ge=1, le=50),
) -> Dict[str, Any]:
    """Preview feed entries without ingesting them into SQLite."""
    resolved = rss_client.resolve_feed_url(url)
    parsed = await rss_client.fetch_feed(resolved)
    feed_header = parsed.get("feed", {})
    entries = parsed.get("entries", [])[:limit]

    clean_entries = []
    for e in entries:
        clean_entries.append({
            "id": e.get("id") or e.get("guid") or e.get("link"),
            "title": e.get("title"),
            "link": e.get("link"),
            "published": e.get("published"),
            "summary": (e.get("summary") or "")[:300],
        })

    return {
        "url": resolved,
        "feed_title": feed_header.get("title"),
        "feed_description": feed_header.get("description"),
        "count": len(clean_entries),
        "entries": clean_entries,
    }
