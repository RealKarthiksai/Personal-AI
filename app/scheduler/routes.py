"""FastAPI router for background scheduler management and job inspection."""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException

from app.scheduler.manager import scheduler_manager

router = APIRouter(prefix="/api/scheduler", tags=["Background Scheduler"])


@router.get("/status")
async def get_scheduler_status() -> Dict[str, Any]:
    """Check scheduler status and active job count."""
    jobs = scheduler_manager.get_jobs()
    return {
        "running": scheduler_manager.is_running(),
        "job_count": len(jobs),
        "jobs": jobs,
    }


@router.get("/jobs")
async def list_jobs() -> List[Dict[str, Any]]:
    """List all scheduled background jobs."""
    return scheduler_manager.get_jobs()


@router.post("/jobs/{job_id}/trigger")
async def trigger_job(job_id: str) -> Dict[str, Any]:
    """Manually trigger a scheduled job immediately."""
    result = await scheduler_manager.trigger_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or scheduler not running")
    return {
        "job_id": job_id,
        "status": "executed",
        "result": result,
    }


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> Dict[str, Any]:
    """Pause a scheduled job."""
    success = scheduler_manager.pause_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or scheduler not running")
    return {"job_id": job_id, "status": "paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> Dict[str, Any]:
    """Resume a paused scheduled job."""
    success = scheduler_manager.resume_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or scheduler not running")
    return {"job_id": job_id, "status": "resumed"}
