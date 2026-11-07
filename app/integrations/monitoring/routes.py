"""FastAPI router for website monitoring and change detection."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.integrations.monitoring.service import monitoring_service

router = APIRouter(prefix="/api/integrations/monitoring", tags=["Website Monitoring"])


class CreateWatchRequest(BaseModel):
    url: str = Field(..., description="Target webpage URL to monitor")
    title: Optional[str] = Field(default=None, description="Descriptive title for this watch")
    watch_id: Optional[str] = Field(default=None, description="Custom unique watch ID")


class CheckRequest(BaseModel):
    watch_id: Optional[str] = Field(default=None, description="Specific watch ID to check. If omitted, checks all watches.")


@router.get("/watches")
async def list_watches() -> List[Dict[str, Any]]:
    """List all registered website watches."""
    return monitoring_service.list_watches()


@router.post("/watches")
async def create_watch(payload: CreateWatchRequest) -> Dict[str, Any]:
    """Register a new webpage to monitor for changes."""
    return monitoring_service.create_watch(
        url=payload.url,
        title=payload.title,
        watch_id=payload.watch_id,
    )


@router.delete("/watches/{watch_id}")
async def delete_watch(watch_id: str) -> Dict[str, Any]:
    """Remove a website watch."""
    success = monitoring_service.delete_watch(watch_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Watch '{watch_id}' not found")
    return {"status": "deleted", "watch_id": watch_id}


@router.post("/check")
async def check_watches(payload: Optional[CheckRequest] = None) -> Dict[str, Any]:
    """Run differential check on one or all watches."""
    target_id = payload.watch_id if payload else None
    if target_id:
        watches = [w for w in monitoring_service.list_watches() if w["watch_id"] == target_id]
        if not watches:
            raise HTTPException(status_code=404, detail=f"Watch '{target_id}' not found")
        return await monitoring_service.check_watch(watches[0])
    return await monitoring_service.check_all_watches()


@router.post("/webhook")
async def receive_changedetection_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Inbound webhook receiver for ChangeDetection.io alerts."""
    return await monitoring_service.handle_webhook(payload)
