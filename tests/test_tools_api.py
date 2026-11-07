"""API tests for tools endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.database.models import ExtractedContent, SearchResult
from app.main import app

client = TestClient(app)


def test_tools_status():
    resp = client.get("/api/v1/tools/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "searxng" in data
    assert "crawl4ai" in data


def test_api_search():
    mock_results = [
        SearchResult(title="Result A", url="https://a.org", snippet="Snippet A", engine="bing")
    ]
    with patch("app.services.search_service.search_service.search", new_callable=AsyncMock, return_value=mock_results):
        resp = client.post(
            "/api/v1/tools/search",
            json={"query": "test query", "num_results": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test query"
    assert data["count"] == 1
    assert data["results"][0]["title"] == "Result A"


def test_api_extract():
    mock_extracted = ExtractedContent(
        url="https://article.com",
        title="Article Title",
        markdown="Article Markdown",
        success=True,
    )
    with patch("app.services.extractor_service.extractor_service.extract", new_callable=AsyncMock, return_value=mock_extracted):
        resp = client.post(
            "/api/v1/tools/extract",
            json={"url": "https://article.com"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://article.com"
    assert data["title"] == "Article Title"
    assert data["success"] is True
