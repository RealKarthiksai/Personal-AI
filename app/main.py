"""FastAPI application entry point.

Wires together health routes, initializes logging and the database
on startup, and exposes the ASGI app for uvicorn.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import health as health_module
from app.api.routes import ingestion as ingestion_module
from app.api.routes import tools as tools_module
from app.integrations.github import github_router
from app.integrations.openalex import openalex_router
from app.integrations.reddit import reddit_router
from app.integrations.rss import rss_router
from app.scheduler import scheduler_manager, scheduler_router
from app.config import config
from app.database import database
from app.utils.logging import configure_logging, get_logger

logger = get_logger("app.main")

configure_logging(level=logging.INFO)

app = FastAPI(
    title="Local AI Chatbot (Karna)",
    description="Replies via a local llama.cpp LLM across configured messaging channels with live web search and extraction.",
    version="0.1.0",
)

# Include routers.
app.include_router(health_module.router)
app.include_router(tools_module.router)
app.include_router(ingestion_module.router)
app.include_router(github_router)
app.include_router(openalex_router)
app.include_router(reddit_router)
app.include_router(rss_router)
app.include_router(scheduler_router)


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize the database and log configuration status (no secrets)."""
    database.init_db()
    scheduler_manager.start()
    logger.info(
        "Application starting | env=%s | llm=%s | telegram=%s | searxng=%s",
        config.app_env,
        "configured" if config.is_llm_configured() else "NOT configured",
        "configured" if config.is_telegram_configured() else "NOT configured",
        "configured" if config.is_searxng_configured() else "NOT configured",
        extra={"request_id": "system", "message_id": "system"},
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Shut down background scheduler and background tasks."""
    scheduler_manager.shutdown()


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": "Local AI Chatbot (Karna)",
        "version": "0.1.0",
        "endpoints": [
            "/health",
            "/api/v1/tools/search",
            "/api/v1/tools/extract",
            "/api/v1/tools/status",
        ],
    }