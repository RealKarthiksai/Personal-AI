"""OpenAlex API integration package."""

from app.integrations.openalex.client import OpenAlexClient, openalex_client
from app.integrations.openalex.service import OpenAlexService, openalex_service
from app.integrations.openalex.routes import router as openalex_router

__all__ = ["OpenAlexClient", "openalex_client", "OpenAlexService", "openalex_service", "openalex_router"]
