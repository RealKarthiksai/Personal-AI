"""FastAPI application entry point.

Wires together health routes, initializes logging and the database
on startup, and exposes the ASGI app for uvicorn.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import health as health_module
from app.config import config
from app.database import database
from app.utils.logging import configure_logging, get_logger

logger = get_logger("app.main")

configure_logging(level=logging.INFO)

app = FastAPI(
    title="Local AI Chatbot (Karna)",
    description="Replies via a local llama.cpp LLM across configured messaging channels.",
    version="0.1.0",
)

# Include routers.
app.include_router(health_module.router)


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize the database and log configuration status (no secrets)."""
    database.init_db()
    logger.info(
        "Application starting | env=%s | llm=%s | telegram=%s",
        config.app_env,
        "configured" if config.is_llm_configured() else "NOT configured",
        "configured" if config.is_telegram_configured() else "NOT configured",
        extra={"request_id": "system", "message_id": "system"},
    )


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": "Local AI Chatbot (Karna)",
        "version": "0.1.0",
        "endpoints": ["/health"],
    }