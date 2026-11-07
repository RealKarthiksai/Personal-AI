"""Unit tests for background scheduler manager and endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.database import database
from app.main import app
from app.scheduler.manager import SchedulerManager


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """Provide a fresh SQLite database for each test."""
    db_file = tmp_path / "test_scheduler.db"
    import app.config as cfg_module

    orig_url = cfg_module.config.database_url
    cfg_module.config.database_url = f"sqlite:///{db_file}"
    database._init_lock = False
    database.init_db()
    yield
    cfg_module.config.database_url = orig_url


@pytest.mark.asyncio
async def test_scheduler_lifecycle_and_default_jobs() -> None:
    mgr = SchedulerManager()
    mgr.start()
    try:
        assert mgr.is_running() is True
        jobs = mgr.get_jobs()
        job_ids = [j["id"] for j in jobs]
        assert "rss_sync" in job_ids
        assert "github_trending_sync" in job_ids
        assert "openalex_papers_sync" in job_ids
        assert "reddit_discussions_sync" in job_ids

        # Test pause & resume
        assert mgr.pause_job("rss_sync") is True
        jobs_paused = mgr.get_jobs()
        rss_job = next(j for j in jobs_paused if j["id"] == "rss_sync")
        assert rss_job["paused"] is True

        assert mgr.resume_job("rss_sync") is True
        jobs_resumed = mgr.get_jobs()
        rss_job_resumed = next(j for j in jobs_resumed if j["id"] == "rss_sync")
        assert rss_job_resumed["paused"] is False
    finally:
        mgr.shutdown()
        assert mgr.is_running() is False


@pytest.mark.asyncio
async def test_scheduler_trigger_job() -> None:
    mgr = SchedulerManager()
    mgr.start()
    try:
        with patch("app.scheduler.jobs.rss_service.sync_all_subscriptions", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {
                "feeds_synced": 1,
                "total_inserted": 5,
                "total_updated": 0,
                "details": {},
            }
            res = await mgr.trigger_job("rss_sync")
            assert res is not None
            assert res["total_inserted"] == 5

        # Non-existent job
        res_none = await mgr.trigger_job("non_existent_job_123")
        assert res_none is None
    finally:
        mgr.shutdown()


def test_scheduler_api_routes() -> None:
    client = TestClient(app)

    # 1. Status
    resp = client.get("/api/scheduler/status")
    assert resp.status_code == 200
    status = resp.json()
    assert "running" in status
    assert "job_count" in status

    # 2. List jobs
    resp = client.get("/api/scheduler/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert isinstance(jobs, list)

    # 3. Pause & Resume via API
    resp_pause = client.post("/api/scheduler/jobs/rss_sync/pause")
    if resp_pause.status_code == 200:
        assert resp_pause.json()["status"] == "paused"
        resp_resume = client.post("/api/scheduler/jobs/rss_sync/resume")
        assert resp_resume.status_code == 200
        assert resp_resume.json()["status"] == "resumed"

    # 4. Trigger via API with mock
    with patch("app.scheduler.manager.scheduler_manager.trigger_job", new_callable=AsyncMock) as mock_trigger:
        mock_trigger.return_value = {"inserted": 2, "updated": 0}
        resp_trig = client.post("/api/scheduler/jobs/rss_sync/trigger")
        assert resp_trig.status_code == 200
        assert resp_trig.json()["status"] == "executed"
        assert resp_trig.json()["result"]["inserted"] == 2
