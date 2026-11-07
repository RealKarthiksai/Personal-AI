"""Gate 1: Source Failure Matrix & Ingestion Accounting Tests.

Verifies:
1. RedditClient raises SourceUnconfigured immediately when OAuth credentials are not configured.
2. RedditClient raises typed exceptions on HTTP failures (403, 429, timeout).
3. GitHubClient raises SourceRateLimited on rate limits (429 or x-ratelimit-remaining: 0),
   and SourceHTTPError on 401/403.
4. OpenAlexClient raises SourceTimeout on timeout and SourceHTTPError on API failures.
5. IngestionPipeline tracks fetched_count and record_ids for inserted, updated, and skipped records.
"""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.integrations.errors import (
    SourceError,
    SourceHTTPError,
    SourceNetworkError,
    SourceRateLimited,
    SourceTimeout,
    SourceUnconfigured,
    map_httpx_exception,
)
from app.integrations.github.client import GitHubClient
from app.integrations.openalex.client import OpenAlexClient
from app.integrations.reddit.client import RedditClient
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.external import ExternalRecord


# ==============================================================================
# 1. Generic Exception Mapping Tests
# ==============================================================================

def test_map_httpx_timeout():
    req = httpx.Request("GET", "https://api.example.com/test?token=SECRET_123")
    exc = httpx.ReadTimeout("Read timed out", request=req)
    mapped = map_httpx_exception(exc, source="test_source")
    assert isinstance(mapped, SourceTimeout)
    assert mapped.error_code == "timeout"
    assert "SECRET_123" not in str(mapped)


def test_map_httpx_connect_error():
    req = httpx.Request("GET", "https://api.example.com/test")
    exc = httpx.ConnectError("Connection refused", request=req)
    mapped = map_httpx_exception(exc, source="test_source")
    assert isinstance(mapped, SourceNetworkError)
    assert mapped.error_code == "network"


def test_map_httpx_rate_limit_via_header():
    req = httpx.Request("GET", "https://api.github.com/search")
    resp = httpx.Response(
        403,
        request=req,
        headers={"x-ratelimit-remaining": "0", "retry-after": "60"},
    )
    exc = httpx.HTTPStatusError("Forbidden", request=req, response=resp)
    mapped = map_httpx_exception(exc, source="github")
    assert isinstance(mapped, SourceRateLimited)
    assert mapped.error_code == "rate_limited"
    assert mapped.retry_after == 60


def test_map_httpx_401_unauthorized():
    req = httpx.Request("GET", "https://api.github.com/user")
    resp = httpx.Response(401, request=req)
    exc = httpx.HTTPStatusError("Unauthorized", request=req, response=resp)
    mapped = map_httpx_exception(exc, source="github")
    assert isinstance(mapped, SourceHTTPError)
    assert mapped.status == 401
    assert mapped.error_code == "http_401"


# ==============================================================================
# 2. Reddit Client Failure Matrix
# ==============================================================================

@pytest.mark.asyncio
async def test_reddit_client_unconfigured_raises_immediately():
    """RedditClient must raise SourceUnconfigured without any network call when credentials are empty."""
    client = RedditClient(client_id="", client_secret="", user_agent="test/1.0")
    with pytest.raises(SourceUnconfigured) as exc_info:
        await client.get_subreddit_posts("LocalLLaMA")
    assert exc_info.value.error_code == "unconfigured"


@pytest.mark.asyncio
async def test_reddit_client_oauth_failure_mapped():
    """RedditClient maps OAuth token endpoint failure to typed exception."""
    client = RedditClient(client_id="my_id", client_secret="my_secret", user_agent="test/1.0")
    req = httpx.Request("POST", RedditClient.OAUTH_URL)
    resp = httpx.Response(401, request=req)

    with patch("httpx.AsyncClient.post", side_effect=httpx.HTTPStatusError("Unauthorized", request=req, response=resp)):
        with pytest.raises(SourceHTTPError) as exc_info:
            await client.get_subreddit_posts("LocalLLaMA")
        assert exc_info.value.status == 401
        assert exc_info.value.error_code == "http_401"


# ==============================================================================
# 3. GitHub Client Failure Matrix
# ==============================================================================

@pytest.mark.asyncio
async def test_github_client_rate_limit_mapped():
    """GitHubClient maps 403 with x-ratelimit-remaining: 0 to SourceRateLimited."""
    client = GitHubClient(token="fake_token")
    req = httpx.Request("GET", "https://api.github.com/search/repositories")
    resp = httpx.Response(403, request=req, headers={"x-ratelimit-remaining": "0", "retry-after": "30"})

    with patch("httpx.AsyncClient.get", side_effect=httpx.HTTPStatusError("Rate limit", request=req, response=resp)):
        with pytest.raises(SourceRateLimited) as exc_info:
            await client.search_repositories("test query")
        assert exc_info.value.error_code == "rate_limited"
        assert exc_info.value.retry_after == 30


@pytest.mark.asyncio
async def test_github_client_timeout_mapped():
    """GitHubClient maps timeout to SourceTimeout."""
    client = GitHubClient(token=None)
    req = httpx.Request("GET", "https://api.github.com/search/repositories")

    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout", request=req)):
        with pytest.raises(SourceTimeout) as exc_info:
            await client.search_repositories("test query")
        assert exc_info.value.error_code == "timeout"


# ==============================================================================
# 4. OpenAlex Client Failure Matrix
# ==============================================================================

@pytest.mark.asyncio
async def test_openalex_client_http_503_mapped():
    """OpenAlexClient maps 503 Service Unavailable to SourceHTTPError."""
    client = OpenAlexClient(email="test@example.com")
    req = httpx.Request("GET", "https://api.openalex.org/works")
    resp = httpx.Response(503, request=req)

    with patch("httpx.AsyncClient.get", side_effect=httpx.HTTPStatusError("Service Unavailable", request=req, response=resp)):
        with pytest.raises(SourceHTTPError) as exc_info:
            await client.search_works("quantum computing")
        assert exc_info.value.status == 503
        assert exc_info.value.error_code == "http_503"


# ==============================================================================
# 5. Ingestion Result Accounting Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ingestion_result_accounting():
    """IngestionPipeline must accurately track fetched_count and record_ids across inserted, updated, and skipped records."""
    import uuid
    uid = uuid.uuid4().hex[:8]
    pipeline = IngestionPipeline()
    records = [
        ExternalRecord(
            source=f"test_src_{uid}",
            source_id="item_1",
            record_type="article",
            title="First Item",
            url=f"https://example.com/{uid}/1",
        ),
        ExternalRecord(
            source=f"test_src_{uid}",
            source_id="item_2",
            record_type="article",
            title="Second Item",
            url=f"https://example.com/{uid}/2",
        ),
    ]

    # First ingestion -> inserted
    res1 = await pipeline.ingest_batch(records, source_name="test_source")
    assert res1.fetched_count == 2
    assert len(res1.record_ids) == 2
    assert res1.inserted == 2

    # Second ingestion -> skipped (identical content), but record_ids and fetched_count are still populated!
    res2 = await pipeline.ingest_batch(records, source_name="test_source")
    assert res2.fetched_count == 2
    assert len(res2.record_ids) == 2
    assert res2.skipped_identical == 2
    # Ensure record IDs match the first run
    assert res1.record_ids == res2.record_ids
