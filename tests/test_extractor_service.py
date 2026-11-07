"""Unit tests for ExtractorService."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.database import repository
from app.database.models import ExtractedContent
from app.services.extractor_service import ExtractorService


@pytest.fixture
def extractor_svc():
    return ExtractorService(max_content_chars=500, timeout_seconds=2)


def test_is_valid_url(extractor_svc):
    assert extractor_svc.is_valid_url("https://example.com") is True
    assert extractor_svc.is_valid_url("http://localhost:8080/test") is True
    assert extractor_svc.is_valid_url("not a url") is False
    assert extractor_svc.is_valid_url("") is False


def test_format_for_llm(extractor_svc):
    content = ExtractedContent(
        url="https://example.com",
        title="Example Title",
        markdown="Sample markdown body content.",
        success=True,
    )
    formatted = extractor_svc.format_for_llm(content)
    assert "[Example Title](https://example.com)" in formatted
    assert "Sample markdown body content." in formatted


@pytest.mark.asyncio
async def test_extractor_cache_hit(extractor_svc, monkeypatch):
    cached_row = {
        "url": "https://cached-example.com",
        "title": "Cached Example",
        "markdown_content": "Previously crawled content.",
        "created_at": "2026-11-07 10:00:00",
    }
    monkeypatch.setattr(
        repository,
        "get_cached_page",
        lambda url_hash, max_age_seconds: cached_row,
    )

    result = await extractor_svc.extract("https://cached-example.com")
    assert result.success is True
    assert result.title == "Cached Example"
    assert result.markdown == "Previously crawled content."


@pytest.mark.asyncio
async def test_extractor_fallback_success(extractor_svc, monkeypatch):
    monkeypatch.setattr(repository, "get_cached_page", lambda url_hash, max_age_seconds: None)
    cached_writes = []
    monkeypatch.setattr(
        repository,
        "set_cached_page",
        lambda url_hash, url, title, markdown_content: cached_writes.append((url, title)),
    )
    monkeypatch.setattr(
        repository,
        "log_tool_execution",
        lambda tool_name, input_data, output_summary, duration_ms: 1,
    )

    # Force Crawl4AI to fail to trigger HTTP fallback
    with patch.object(extractor_svc, "_extract_crawl4ai", side_effect=RuntimeError("Browser error")):
        with patch.object(
            extractor_svc,
            "_extract_fast_http",
            return_value=ExtractedContent(
                url="https://fallback.com",
                title="Fallback Site",
                markdown="Extracted via HTTP fallback.",
                success=True,
            ),
        ):
            result = await extractor_svc.extract("https://fallback.com")

    assert result.success is True
    assert result.title == "Fallback Site"
    assert len(cached_writes) == 1
