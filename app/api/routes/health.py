"""GET /health — application health check.

Health information never reveals credentials or sensitive data.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import config

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "app_env": config.app_env,
        "llm_configured": config.is_llm_configured(),
        "telegram_configured": config.is_telegram_configured(),
    }