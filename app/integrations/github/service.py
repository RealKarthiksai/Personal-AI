"""GitHub integration service.

Converts GitHub API responses into normalized ExternalRecord objects and saves
them into the SQLite repository via the Common Ingestion Pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.integrations.github.client import GitHubClient, github_client
from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.schemas.external import ExternalRecord, IngestionResult
from app.utils.logging import get_logger

logger = get_logger("app.integrations.github.service")


class GitHubService:
    """Orchestrates GitHub API data extraction and ingestion."""

    def __init__(
        self,
        client: Optional[GitHubClient] = None,
        ingestion_pipeline: Optional[IngestionPipeline] = None,
    ) -> None:
        self.client = client or github_client
        self.pipeline = ingestion_pipeline or default_pipeline

    def map_repository_to_record(self, item: Dict[str, Any]) -> ExternalRecord:
        """Map raw GitHub repository dict to ExternalRecord."""
        full_name = item.get("full_name") or f"{item.get('owner', {}).get('login')}/{item.get('name')}"
        meta = {
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "language": item.get("language"),
            "topics": item.get("topics", []),
            "open_issues": item.get("open_issues_count", 0),
            "owner": item.get("owner", {}).get("login"),
            "default_branch": item.get("default_branch", "main"),
        }
        return ExternalRecord(
            source="github",
            source_id=full_name,
            record_type="repository",
            title=full_name,
            url=item.get("html_url", f"https://github.com/{full_name}"),
            description=item.get("description"),
            published_at=item.get("created_at"),
            updated_at=item.get("pushed_at") or item.get("updated_at"),
            metadata=meta,
        )

    # Alias for convenience
    map_repo_to_record = map_repository_to_record

    def map_release_to_record(self, owner: str, repo: str, item: Dict[str, Any]) -> ExternalRecord:
        """Map raw GitHub release dict to ExternalRecord."""
        tag = item.get("tag_name") or str(item.get("id"))
        release_id = f"{owner}/{repo}@{tag}"
        name = item.get("name") or tag
        title = f"{owner}/{repo} - Release {name}"
        meta = {
            "repo": f"{owner}/{repo}",
            "tag": tag,
            "prerelease": item.get("prerelease", False),
            "draft": item.get("draft", False),
            "author": item.get("author", {}).get("login"),
        }
        return ExternalRecord(
            source="github",
            source_id=release_id,
            record_type="release",
            title=title,
            url=item.get("html_url", f"https://github.com/{owner}/{repo}/releases/tag/{tag}"),
            description=item.get("body"),
            published_at=item.get("published_at") or item.get("created_at"),
            updated_at=item.get("published_at"),
            metadata=meta,
        )

    async def search_and_ingest(
        self,
        query: str,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 20,
        limit: Optional[int] = None,
    ) -> IngestionResult:
        """Search repositories and ingest into SQLite."""
        effective_per_page = limit or per_page
        items = await self.client.search_repositories(query=query, sort=sort, order=order, per_page=effective_per_page)
        records = [self.map_repository_to_record(item) for item in items if item.get("html_url")]
        return await self.pipeline.ingest_batch(records, source_name="github")

    async def discover_trending_and_ingest(
        self,
        language: Optional[str] = None,
        topic: Optional[str] = None,
        since_days: int = 7,
        min_stars: int = 50,
        per_page: int = 20,
    ) -> IngestionResult:
        """Discover trending repositories and ingest into SQLite."""
        items = await self.client.get_trending(
            language=language,
            topic=topic,
            since_days=since_days,
            min_stars=min_stars,
            per_page=per_page,
        )
        records = [self.map_repository_to_record(item) for item in items if item.get("html_url")]
        return await self.pipeline.ingest_batch(records, source_name="github")

    async def fetch_releases_and_ingest(
        self,
        owner: str,
        repo: str,
        per_page: int = 10,
    ) -> IngestionResult:
        """Fetch releases for a repository and ingest into SQLite."""
        items = await self.client.get_releases(owner=owner, repo=repo, per_page=per_page)
        records = [self.map_release_to_record(owner, repo, item) for item in items if item.get("html_url")]
        return await self.pipeline.ingest_batch(records, source_name="github")


github_service = GitHubService()
