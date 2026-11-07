"""Scheduler manager wrapping APScheduler AsyncIOScheduler.

Provides lifecycle management, job registration, pause/resume, and immediate triggering.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import config
from app.scheduler.jobs import (
    job_check_monitored_websites,
    job_memory_idle,
    job_memory_nightly,
    job_sync_github_trending,
    job_sync_openalex_papers,
    job_sync_reddit_discussions,
    job_sync_rss_feeds,
)
from app.utils.logging import get_logger

logger = get_logger("app.scheduler.manager")


class SchedulerManager:
    """Manages background scheduled ingestion and maintenance tasks."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._is_started = False

    def register_default_jobs(self) -> None:
        """Register default scheduled background tasks."""
        # 1. RSS Feeds Sync
        rss_mins = max(1, config.rss_sync_interval_minutes)
        self.scheduler.add_job(
            job_sync_rss_feeds,
            trigger=IntervalTrigger(minutes=rss_mins),
            id="rss_sync",
            name="RSS Subscriptions Sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 2. GitHub Trending Discovery
        gh_hours = max(1, config.github_sync_interval_hours)
        self.scheduler.add_job(
            job_sync_github_trending,
            trigger=IntervalTrigger(hours=gh_hours),
            id="github_trending_sync",
            name="GitHub Trending AI Repositories Sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 3. OpenAlex Literature Sync
        oa_hours = max(1, config.openalex_sync_interval_hours)
        self.scheduler.add_job(
            job_sync_openalex_papers,
            trigger=IntervalTrigger(hours=oa_hours),
            id="openalex_papers_sync",
            name="OpenAlex Academic Papers Sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 4. Reddit Discussions Sync
        rd_hours = max(1, config.reddit_sync_interval_hours)
        self.scheduler.add_job(
            job_sync_reddit_discussions,
            trigger=IntervalTrigger(hours=rd_hours),
            id="reddit_discussions_sync",
            name="Reddit LocalLLaMA Discussions Sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 5. Website Change Monitoring Check
        mon_hours = max(1, config.monitoring_check_interval_hours)
        self.scheduler.add_job(
            job_check_monitored_websites,
            trigger=IntervalTrigger(hours=mon_hours),
            id="website_monitoring_check",
            name="Website Differential Change Monitor",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 6. Nightly Memory Tier Decay, Consolidation & Online Backup (03:00 IST / 21:30 UTC)
        self.scheduler.add_job(
            job_memory_nightly,
            trigger=CronTrigger(hour=21, minute=30, timezone="UTC"),
            id="memory_nightly_decay",
            name="Nightly Memory Decay & Database Backup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 7. Idle Memory Consolidation (every 30m)
        self.scheduler.add_job(
            job_memory_idle,
            trigger=IntervalTrigger(minutes=30),
            id="memory_idle_consolidation",
            name="Idle Memory Fact Consolidation",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        logger.info(
            "Registered default background jobs | rss=%dm | github=%dh | openalex=%dh | reddit=%dh | monitoring=%dh | memory_nightly=21:30UTC | memory_idle=30m",
            rss_mins,
            gh_hours,
            oa_hours,
            rd_hours,
            mon_hours,
        )

    def start(self) -> None:
        """Start the background scheduler."""
        if not config.scheduler_enabled:
            logger.info("Background scheduler is disabled via config (SCHEDULER_ENABLED=false)")
            return

        if self._is_started:
            return

        self.register_default_jobs()
        try:
            self.scheduler.start()
            self._is_started = True
            logger.info("Background scheduler started successfully")
        except RuntimeError as exc:
            logger.warning("Could not start AsyncIOScheduler immediately: %s", exc)

    def shutdown(self) -> None:
        """Gracefully shut down the background scheduler."""
        if self._is_started:
            try:
                self.scheduler.shutdown(wait=False)
                self._is_started = False
                logger.info("Background scheduler shut down")
            except Exception as exc:
                logger.warning("Error shutting down scheduler: %s", exc)

    def is_running(self) -> bool:
        """Check if scheduler is currently active."""
        return self._is_started and self.scheduler.running

    def get_jobs(self) -> List[Dict[str, Any]]:
        """List all scheduled jobs with their metadata and next run times."""
        if not self._is_started:
            return []

        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run,
                "trigger": str(job.trigger),
                "paused": job.next_run_time is None,
            })
        return jobs

    async def trigger_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Manually execute a scheduled job immediately and return its result."""
        job = self.scheduler.get_job(job_id) if self._is_started else None
        if not job:
            return None

        logger.info("Manually executing job: %s", job_id)
        # Execute the underlying callable directly
        if inspect.iscoroutinefunction(job.func):
            return await job.func()
        else:
            return job.func()

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        job = self.scheduler.get_job(job_id) if self._is_started else None
        if not job:
            return False
        job.pause()
        logger.info("Paused job: %s", job_id)
        return True

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused scheduled job."""
        job = self.scheduler.get_job(job_id) if self._is_started else None
        if not job:
            return False
        job.resume()
        logger.info("Resumed job: %s", job_id)
        return True


scheduler_manager = SchedulerManager()
