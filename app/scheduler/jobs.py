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


async def job_memory_nightly() -> Dict[str, Any]:
    """Nightly memory tier decay, consolidation, raw message purge, and online backup."""
    from app.config import config
    from app.database.database import transaction
    from app.memory.decay import (
        backup_database_online,
        cleanup_expired_raw_messages,
        run_tier_decay_for_user,
    )
    from app.memory.repository import log_memory_job

    start_time = datetime.now(timezone.utc).isoformat()
    logger.info("Starting scheduled nightly memory decay & backup")

    try:
        user_ids: List[int] = []
        with transaction() as conn:
            rows = conn.execute("SELECT id FROM users").fetchall()
            user_ids = [int(r["id"]) for r in rows]

        total_promoted = 0
        total_dropped = 0
        total_retained = 0

        for uid in user_ids:
            stats = run_tier_decay_for_user(uid)
            total_promoted += stats.get("promoted_weekly", 0) + stats.get("promoted_monthly", 0)
            total_dropped += stats.get("dropped", 0)
            total_retained += stats.get("retained", 0)

        cleaned_msgs = cleanup_expired_raw_messages(retention_days=config.memory_raw_retention_days)
        backup_path = backup_database_online()

        log_memory_job(
            job_name="nightly_decay",
            status="success",
            items_decayed=total_dropped,
            items_promoted=total_promoted,
            details=f"Cleaned {cleaned_msgs} expired raw messages. Backup: {backup_path}",
        )

        logger.info(
            "Scheduled nightly memory decay completed | users=%d | promoted=%d | dropped=%d | retained=%d | backup=%s",
            len(user_ids),
            total_promoted,
            total_dropped,
            total_retained,
            backup_path,
        )
        return {
            "users_processed": len(user_ids),
            "promoted": total_promoted,
            "dropped": total_dropped,
            "retained": total_retained,
            "cleaned_messages": cleaned_msgs,
            "backup_path": backup_path,
        }
    except Exception as exc:
        logger.error("Nightly memory decay failed: %s", exc)
        log_memory_job(
            job_name="nightly_decay",
            status="failed",
            error_message=str(exc),
        )
        return {"error": str(exc)}


async def job_memory_idle() -> Dict[str, Any]:
    """Process un-extracted messages during idle cycles."""
    from app.config import config
    from app.database.database import transaction
    from app.memory.config import get_memory_profile
    from app.memory.extractor import extract_all_facts, extract_facts_rules
    from app.memory.models import MemoryItem, MemorySource, MemoryTier
    from app.memory.profile import update_profile_from_fact
    from app.memory.repository import log_memory_job, save_memory
    from app.services.llm_client import LLMClient

    start_time = datetime.now(timezone.utc).isoformat()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    period_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        unprocessed_msgs: List[Dict[str, Any]] = []
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, channel, text, created_at
                FROM messages
                WHERE memory_processed_at IS NULL
                  AND direction = 'inbound'
                ORDER BY id ASC
                LIMIT 20
                """
            ).fetchall()
            for r in rows:
                unprocessed_msgs.append({
                    "id": r["id"],
                    "user_id": r["user_id"] or 1,
                    "channel": r["channel"] or "telegram",
                    "text": r["text"],
                })

        if not unprocessed_msgs:
            return {"processed_messages": 0, "facts_extracted": 0}

        profile = get_memory_profile()
        llm = LLMClient() if profile.llm_extraction_enabled else None
        extracted_facts_count = 0

        for msg in unprocessed_msgs:
            uid = msg["user_id"]
            channel = msg["channel"]
            txt = msg["text"]
            mid = msg["id"]

            try:
                if llm is not None:
                    facts = await extract_all_facts(txt, llm_client=llm, message_id=mid)
                else:
                    facts = extract_facts_rules(txt, message_id=mid)

                for f in facts:
                    mem_item = MemoryItem(
                        id=None,
                        user_id=uid,
                        tier=MemoryTier.CORE if f.profile_key == "name" else MemoryTier.DAILY,
                        period=period_str,
                        text=f.text,
                        importance=f.importance,
                        confidence=f.confidence,
                        category=f.category,
                        source=MemorySource.LLM if llm is not None else MemorySource.RULE,
                        source_snippet=f.source_snippet,
                        source_message_ids=[mid] if mid else [],
                        source_channels=[channel],
                    )
                    saved_id = save_memory(mem_item)
                    if f.profile_key and f.profile_value:
                        update_profile_from_fact(
                            user_id=uid,
                            key=f.profile_key,
                            value=f.profile_value,
                            memory_id=saved_id,
                        )
                    extracted_facts_count += 1

                with transaction() as conn:
                    conn.execute(
                        "UPDATE messages SET memory_processed_at = ? WHERE id = ?",
                        (now_str, mid),
                    )
            except Exception as e:
                logger.warning("Failed extracting facts for message %d: %s", mid, e)
                with transaction() as conn:
                    conn.execute(
                        "UPDATE messages SET memory_processed_at = ? WHERE id = ?",
                        (now_str, mid),
                    )

        log_memory_job(
            job_name="idle_consolidation",
            status="success",
            items_promoted=extracted_facts_count,
            details=f"Processed {len(unprocessed_msgs)} messages",
        )
        return {
            "processed_messages": len(unprocessed_msgs),
            "facts_extracted": extracted_facts_count,
        }
    except Exception as exc:
        logger.error("Idle memory processing job failed: %s", exc)
        log_memory_job(
            job_name="idle_consolidation",
            status="failed",
            error_message=str(exc),
        )
        return {"error": str(exc)}

