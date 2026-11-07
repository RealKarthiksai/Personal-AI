"""Unit tests for SearchService."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.database import repository
from app.database.models import SearchResult
from app.services.search_service import SearchService, SearchServiceError


@pytest.fixture
def search_svc(tmp_path):
    return SearchService(
        base_url="http://mock-searxng:8080",
        cache_ttl_seconds=3600,
        timeout_seconds=2.0,
    )


def test_query_hashing():
    h1 = SearchService._hash_query("  Python   Programming  ")
    h2 = SearchService._hash_query("python programming")
    assert h1 == h2


def test_format_for_llm(search_svc):
    results = [
        SearchResult(title="Doc 1", url="https://example.com/1", snippet="Snippet 1"),
        SearchResult(title="Doc 2", url="https://example.com/2", snippet="Snippet 2"),
    ]
    formatted = search_svc.format_for_llm(results)
    assert "Web Search Results:" in formatted
    assert "[Doc 1](https://example.com/1)" in formatted
    assert "Snippet 1" in formatted


@pytest.mark.asyncio
async def test_search_cache_hit(search_svc, monkeypatch):
    cached_data = [
        {"title": "Cached Title", "url": "https://cached.org", "snippet": "Cached snippet", "engine": "google"}
    ]
    monkeypatch.setattr(
        repository,
        "get_cached_search",
        lambda query_hash, max_age_seconds: json.dumps(cached_data),
    )

    results = await search_svc.search("cached query")
    assert len(results) == 1
    assert results[0].title == "Cached Title"
    assert results[0].url == "https://cached.org"


@pytest.mark.asyncio
async def test_search_api_success(search_svc, monkeypatch):
    monkeypatch.setattr(repository, "get_cached_search", lambda query_hash, max_age_seconds: None)
    cached_writes = []
    monkeypatch.setattr(
        repository,
        "set_cached_search",
        lambda query_hash, query, results_json: cached_writes.append((query, results_json)),
    )
    monkeypatch.setattr(
        repository,
        "log_tool_execution",
        lambda tool_name, input_data, output_summary, duration_ms: 1,
    )

    fake_searx_payload = {
        "results": [
            {
                "title": "Python Website",
                "url": "https://www.python.org",
                "content": "Official home of Python",
                "engine": "duckduckgo",
            }
        ]
    }

    mock_resp = httpx.Response(
        status_code=200,
        request=httpx.Request("GET", "http://mock-searxng:8080/search"),
        json=fake_searx_payload,
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        results = await search_svc.search("python")

    assert len(results) == 1
    assert results[0].title == "Python Website"
    assert results[0].url == "https://www.python.org"
    assert len(cached_writes) == 1


@pytest.mark.asyncio
async def test_search_api_failure(search_svc, monkeypatch):
    monkeypatch.setattr(repository, "get_cached_search", lambda query_hash, max_age_seconds: None)
    monkeypatch.setattr(
        repository,
        "log_tool_execution",
        lambda tool_name, input_data, output_summary, duration_ms: 1,
    )

    mock_resp = httpx.Response(
        status_code=500,
        request=httpx.Request("GET", "http://mock-searxng:8080/search"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(SearchServiceError):
            await search_svc.search("error query")
