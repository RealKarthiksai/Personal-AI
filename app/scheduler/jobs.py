"""Periodic background jobs executed by APScheduler.

Each job pulls the latest updates from official APIs and feeds, ingests them via the
Common Ingestion Pipeline, and logs audit metrics into SQLite `ingestion_runs`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.ingestion.storage import log_ingestion_run
from app.integrations.github.service import github_service
from app.integrations.openalex.service import openalex_service
from app.integrations.reddit.service import reddit_service
from app.integrations.rss.service import rss_service
from app.utils.logging import get_logger

logger = get_logger("app.scheduler.jobs")


async def job_sync_rss_feeds() -> Dict[str, Any]:
    """Sync all active RSS and Atom feed subscriptions."""
    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled RSS feeds sync")
    try:
        summary = await rss_service.sync_all_subscriptions()
        log_ingestion_run(
            source="rss",
            status="success",
            records_ingested=summary.get("total_inserted", 0),
            records_updated=summary.get("total_updated", 0),
            started_at=start_time,
        )
        logger.info(
            "Scheduled RSS sync completed | feeds=%d | inserted=%d | updated=%d",
            summary.get("feeds_synced", 0),
            summary.get("total_inserted", 0),
            summary.get("total_updated", 0),
        )
        return summary
    except Exception as exc:
        logger.error("Scheduled RSS sync failed: %s", exc)
        log_ingestion_run(
            source="rss",
            status="error",
            error_message=str(exc),
            started_at=start_time,
        )
        return {"error": str(exc), "total_inserted": 0, "total_updated": 0}


async def job_sync_github_trending() -> Dict[str, Any]:
    """Sync trending LLM/AI repositories from GitHub."""
    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled GitHub trending discovery")
    try:
        res = await github_service.discover_trending_and_ingest(topic="llm", min_stars=50)
        log_ingestion_run(
            source="github",
            status="success",
            records_ingested=res.inserted,
            records_updated=res.updated,
            started_at=start_time,
        )
        logger.info(
            "Scheduled GitHub sync completed | inserted=%d | updated=%d",
            res.inserted,
            res.updated,
        )
        return res.model_dump()
    except Exception as exc:
        logger.error("Scheduled GitHub sync failed: %s", exc)
        log_ingestion_run(
            source="github",
            status="error",
            error_message=str(exc),
            started_at=start_time,
        )
        return {"error": str(exc), "inserted": 0, "updated": 0}


async def job_sync_openalex_papers() -> Dict[str, Any]:
    """Sync recent academic papers from OpenAlex."""
    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled OpenAlex literature sync")
    try:
        res = await openalex_service.fetch_recent_and_ingest(topic="language models")
        log_ingestion_run(
            source="openalex",
            status="success",
            records_ingested=res.inserted,
            records_updated=res.updated,
            started_at=start_time,
        )
        logger.info(
            "Scheduled OpenAlex sync completed | inserted=%d | updated=%d",
            res.inserted,
            res.updated,
        )
        return res.model_dump()
    except Exception as exc:
        logger.error("Scheduled OpenAlex sync failed: %s", exc)
        log_ingestion_run(
            source="openalex",
            status="error",
            error_message=str(exc),
            started_at=start_time,
        )
        return {"error": str(exc), "inserted": 0, "updated": 0}


async def job_sync_reddit_discussions() -> Dict[str, Any]:
    """Sync top discussions from r/LocalLLaMA."""
    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled Reddit discussions sync")
    try:
        res = await reddit_service.fetch_and_ingest(subreddit="LocalLLaMA", listing="hot", limit=25)
        log_ingestion_run(
            source="reddit",
            status="success",
            records_ingested=res.inserted,
            records_updated=res.updated,
            started_at=start_time,
        )
        logger.info(
            "Scheduled Reddit sync completed | inserted=%d | updated=%d",
            res.inserted,
            res.updated,
        )
        return res.model_dump()
    except Exception as exc:
        logger.error("Scheduled Reddit sync failed: %s", exc)
        log_ingestion_run(
            source="reddit",
            status="error",
            error_message=str(exc),
            started_at=start_time,
        )
        return {"error": str(exc), "inserted": 0, "updated": 0}


async def job_check_monitored_websites() -> Dict[str, Any]:
    """Check all registered website watches for content changes."""
    from app.integrations.monitoring.service import monitoring_service

    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled website change monitoring check")
    try:
        summary = await monitoring_service.check_all_watches()
        log_ingestion_run(
            source="monitoring",
            status="success",
            records_ingested=summary.get("changes_detected", 0),
            started_at=start_time,
        )
        logger.info(
            "Scheduled monitoring check completed | watches=%d | changes=%d",
            summary.get("total_watches", 0),
            summary.get("changes_detected", 0),
        )
        return summary
    except Exception as exc:
        logger.error("Scheduled monitoring check failed: %s", exc)
        log_ingestion_run(
            source="monitoring",
            status="error",
            error_message=str(exc),
            started_at=start_time,
        )
        return {"error": str(exc), "total_watches": 0, "changes_detected": 0}
