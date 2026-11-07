"""Reddit API client.

Supports both OAuth authenticated requests (if credentials are provided) and
direct Reddit JSON API endpoints with custom User-Agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.integrations.reddit.client")


class RedditClient:
    """Async client for Reddit API."""

    OAUTH_URL = "https://www.reddit.com/api/v1/access_token"
    OAUTH_API_BASE = "https://oauth.reddit.com"
    PUBLIC_BASE = "https://www.reddit.com"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.client_id = client_id if client_id is not None else config.reddit_client_id
        self.client_secret = client_secret if client_secret is not None else config.reddit_client_secret
        self.user_agent = user_agent or config.reddit_user_agent or "PersonalAI-Karna/1.0"
        self._access_token: Optional[str] = None

    def is_oauth_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _get_oauth_token(self) -> Optional[str]:
        if not self.is_oauth_configured():
            return None
        if self._access_token:
            return self._access_token

        auth = (self.client_id, self.client_secret)
        headers = {"User-Agent": self.user_agent}
        data = {"grant_type": "client_credentials"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.OAUTH_URL, auth=auth, data=data, headers=headers)
                resp.raise_for_status()
                token_data = resp.json()
                self._access_token = token_data.get("access_token")
                return self._access_token
        except Exception as exc:
            logger.warning("Reddit OAuth failed, falling back to public JSON API: %s", exc)
            return None

    async def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        token = await self._get_oauth_token()
        headers = {"User-Agent": self.user_agent}

        if token:
            url = f"{self.OAUTH_API_BASE}{path}"
            headers["Authorization"] = f"Bearer {token}"
        else:
            # Public endpoint format: ensure .json extension
            json_path = path if path.endswith(".json") else f"{path}.json"
            url = f"{self.PUBLIC_BASE}{json_path}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning(
                    "Reddit request to %s returned 403 Forbidden. Unauthenticated requests may be blocked by Reddit; configure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for OAuth.",
                    url,
                )
            elif exc.response.status_code == 429:
                logger.warning("Reddit rate limit exceeded on %s (429)", url)
            else:
                logger.error("Reddit HTTP error on %s: %s", url, exc)
            return {}
        except Exception as exc:
            logger.error("Reddit request failed on %s: %s", url, exc)
            return {}

    def _extract_posts(self, data: Any) -> List[Dict[str, Any]]:
        """Extract child post data dicts from Reddit Listing response."""
        if not isinstance(data, dict):
            return []
        listing = data.get("data", {})
        children = listing.get("children", [])
        return [c.get("data", {}) for c in children if isinstance(c, dict) and "data" in c]

    async def get_subreddit_posts(
        self,
        subreddit: str,
        listing: str = "hot",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Fetch posts from a subreddit (listing: 'hot', 'new', 'top')."""
        clean_sub = subreddit.strip().lstrip("r/").strip("/")
        valid_listing = listing if listing in ("hot", "new", "top", "rising") else "hot"
        path = f"/r/{clean_sub}/{valid_listing}"
        data = await self._request(path, params={"limit": min(limit, 100)})
        return self._extract_posts(data)

    async def search_posts(
        self,
        query: str,
        subreddit: Optional[str] = None,
        sort: str = "relevance",
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Search posts on Reddit or within a specific subreddit."""
        params: Dict[str, Any] = {"q": query, "sort": sort, "limit": min(limit, 100)}
        if subreddit:
            clean_sub = subreddit.strip().lstrip("r/").strip("/")
            path = f"/r/{clean_sub}/search"
            params["restrict_sr"] = "on"
        else:
            path = "/search"

        data = await self._request(path, params=params)
        return self._extract_posts(data)


reddit_client = RedditClient()
