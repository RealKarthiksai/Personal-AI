"""RSS and Atom feeds integration package."""

from app.integrations.rss.client import RSSClient, rss_client
from app.integrations.rss.service import RSSService, rss_service
from app.integrations.rss.routes import router as rss_router

__all__ = ["RSSClient", "rss_client", "RSSService", "rss_service", "rss_router"]
