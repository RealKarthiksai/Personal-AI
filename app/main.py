"""FastAPI application entry point.

Wires together health routes, initializes logging and the database
on startup, and exposes the ASGI app for uvicorn.
Uses the modern ``lifespan`` context manager (deprecated
``@app.on_event`` is avoided).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health as health_module
from app.api.routes import ingestion as ingestion_module
from app.api.routes import tools as tools_module
from app.integrations.github import github_router
from app.integrations.openalex import openalex_router
from app.integrations.reddit import reddit_router
from app.integrations.rss import rss_router
from app.integrations.monitoring import monitoring_router
from app.scheduler import scheduler_manager, scheduler_router
from app.config import config
from app.database import database
from app.utils.logging import configure_logging, get_logger

logger = get_logger("app.main")


def _check_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    """Optional API key check.

    Only enforced when ``config.API_KEY`` is set to a non-empty value.
    If ``API_KEY`` is empty (the default for local dev), every request
    is allowed so that local testing doesn't break.
    """
    if not getattr(config, "API_KEY", None):
        return  # API key auth not configured -> allow all
    if not x_api_key or x_api_key != config.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Startup and shutdown hooks replacing the deprecated @app.on_event."""

    # -------- startup --------
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

    yield  # --- app runs here ---

    # -------- shutdown --------
    scheduler_manager.shutdown()
    logger.info("Application shutting down", extra={"request_id": "system", "message_id": "system"})


app = FastAPI(
    title="Local AI Chatbot (Karna)",
    description="Replies via a local llama.cpp LLM across configured messaging channels with live web search and extraction.",
    version="0.1.0",
    lifespan=lifespan,
)

# Optional global API key check – only active when API_KEY is configured.
# If API_KEY is empty (default local dev), every request passes through.
app.dependency_overrides[_check_api_key] = _check_api_key

# CORS – allow the frontend (served from a different origin) to call the API.
# In a pure-local setup with both frontend and backend on the same origin
# this is effectively a no-op; browsers will still send credentials
# if configured, but we keep it permissive for local/dev usage.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers.
app.include_router(health_module.router)
app.include_router(tools_module.router)
app.include_router(ingestion_module.router)
app.include_router(github_router)
app.include_router(openalex_router)
app.include_router(reddit_router)
app.include_router(rss_router)
app.include_router(monitoring_router)
app.include_router(scheduler_router)


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
