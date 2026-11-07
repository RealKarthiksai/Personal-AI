"""GitHub REST API client.

Handles authenticated or unauthenticated requests for repository search,
trending discovery, releases, issues, and repository metadata.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx

from app.config import config
from app.integrations.errors import map_httpx_exception
from app.utils.logging import get_logger

logger = get_logger("app.integrations.github.client")


class GitHubClient:
    """Async client for GitHub REST API v3."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token if token is not None else config.github_token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PersonalAI-Karna/1.0",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            raise map_httpx_exception(exc, source="github") from exc

    async def search_repositories(
        self,
        query: str,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search GitHub repositories by query string."""
        data = await self._get(
            "/search/repositories",
            params={"q": query, "sort": sort, "order": order, "per_page": min(per_page, 100)},
        )
        return data.get("items", [])

    async def get_trending(
        self,
        language: Optional[str] = None,
        topic: Optional[str] = None,
        since_days: int = 7,
        min_stars: int = 50,
        per_page: int = 20,
    ) -> List[Dict[str, Any]]:
        """Trending-like discovery using recent pushes, star thresholds, and topics."""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
        query_parts = [f"stars:>{min_stars}", f"pushed:>{cutoff_date}"]

        if language:
            query_parts.append(f"language:{language}")
        if topic:
            query_parts.append(f"topic:{topic}")

        query = " ".join(query_parts)
        return await self.search_repositories(query=query, sort="stars", order="desc", per_page=per_page)

    async def get_releases(
        self,
        owner: str,
        repo: str,
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch releases for a given repository."""
        data = await self._get(
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": min(per_page, 50)},
        )
        return data if isinstance(data, list) else []

    async def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch issues for a given repository."""
        data = await self._get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": min(per_page, 50)},
        )
        return data if isinstance(data, list) else []

    async def get_repository(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fetch detailed metadata for a single repository."""
        return await self._get(f"/repos/{owner}/{repo}")


github_client = GitHubClient()
