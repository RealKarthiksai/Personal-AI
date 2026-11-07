"""OpenAlex API client.

Client for querying open scientific literature, research papers, authors,
institutions, and citation metadata from OpenAlex (https://openalex.org).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.integrations.openalex.client")


class OpenAlexClient:
    """Async client for OpenAlex REST API."""

    BASE_URL = "https://api.openalex.org"

    def __init__(self, email: Optional[str] = None) -> None:
        self.email = email if email is not None else config.openalex_email
        self.headers = {
            "Accept": "application/json",
            "User-Agent": f"PersonalAI-Karna/1.0 (mailto:{self.email or 'dev@example.com'})",
        }

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        req_params = dict(params or {})
        if self.email and "mailto" not in req_params:
            req_params["mailto"] = self.email

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=self.headers, params=req_params)
            response.raise_for_status()
            return response.json()

    async def search_works(
        self,
        query: str,
        per_page: int = 20,
        sort: str = "publication_date:desc",
        filter_str: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search works (academic papers) by query string."""
        params: Dict[str, Any] = {
            "search": query,
            "per-page": min(per_page, 50),
            "sort": sort,
        }
        if filter_str:
            params["filter"] = filter_str

        data = await self._get("/works", params=params)
        return data.get("results", [])

    async def get_recent_papers(
        self,
        topic: Optional[str] = None,
        from_publication_date: Optional[str] = None,
        per_page: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent academic papers with optional topic and date filter."""
        filters: List[str] = ["has_doi:true"]
        if from_publication_date:
            filters.append(f"from_publication_date:{from_publication_date}")

        params: Dict[str, Any] = {
            "per-page": min(per_page, 50),
            "sort": "publication_date:desc",
            "filter": ",".join(filters),
        }
        if topic:
            params["search"] = topic

        data = await self._get("/works", params=params)
        return data.get("results", [])

    async def search_authors(self, query: str, per_page: int = 10) -> List[Dict[str, Any]]:
        """Search researchers/authors by name."""
        data = await self._get("/authors", params={"search": query, "per-page": min(per_page, 20)})
        return data.get("results", [])


openalex_client = OpenAlexClient()
