"""Unit tests for ToolRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.models import ExtractedContent, SearchResult
from app.services.tool_router import ToolRouter


@pytest.fixture
def mock_search_svc():
    svc = AsyncMock()
    svc.search.return_value = [
        SearchResult(title="Result 1", url="https://res1.com", snippet="Snippet 1")
    ]
    svc.format_for_llm = MagicMock(return_value="Formatted Search Results")
    return svc


@pytest.fixture
def mock_extractor_svc():
    svc = AsyncMock()
    svc.extract.return_value = ExtractedContent(
        url="https://article.org",
        title="Article Title",
        markdown="Article Markdown Content",
        success=True,
    )
    svc.format_for_llm = MagicMock(return_value="Formatted Webpage Content")
    return svc


@pytest.fixture
def router(mock_search_svc, mock_extractor_svc):
    return ToolRouter(search_svc=mock_search_svc, extractor_svc=mock_extractor_svc)


def test_url_detection(router):
    urls = router.extract_urls("Check out https://github.com/torvalds/linux and http://test.org")
    assert urls == ["https://github.com/torvalds/linux", "http://test.org"]


def test_detect_search_query(router):
    # Explicit command
    assert router.detect_search_query("/search arch linux kernel") == "arch linux kernel"
    # Natural language queries
    assert router.detect_search_query("search for latest Python release") == "latest Python release"
    assert router.detect_search_query("who won the super bowl 2026?") == "the super bowl 2026"
    assert router.detect_search_query("what is the latest stable version of node?") == "stable version of node"
    assert router.detect_search_query("can you find all the hackathons hapennin in hyd this month") == "all the hackathons hapennin in hyd this month"
    # Follow-up with previous query
    assert router.detect_search_query("use searching", previous_query="hackathons in hyd") == "hackathons in hyd"
    assert router.detect_search_query("search it", previous_query="weather in tokyo") == "weather in tokyo"
    # General chatter (should be None)
    assert router.detect_search_query("Hello there, how are you today?") is None
    assert router.detect_search_query("Write a python function to add two numbers") is None


def test_detect_read_url(router):
    assert router.detect_read_url("/read https://news.ycombinator.com") == "https://news.ycombinator.com"
    assert router.detect_read_url("Can you summarize https://example.com/post ?") == "https://example.com/post"
    assert router.detect_read_url("What is AI?") is None


@pytest.mark.asyncio
async def test_route_to_search(router, mock_search_svc):
    res = await router.route_and_execute("search for fast web scraping")
    assert res.tool_name == "searxng_search"
    assert res.input_value == "fast web scraping"
    assert res.context_text == "Formatted Search Results"
    mock_search_svc.search.assert_awaited_once_with("fast web scraping")


@pytest.mark.asyncio
async def test_route_to_extractor(router, mock_extractor_svc):
    res = await router.route_and_execute("Please summarize https://example.com/article")
    assert res.tool_name == "web_extractor"
    assert res.input_value == "https://example.com/article"
    assert res.context_text == "Formatted Webpage Content"
    mock_extractor_svc.extract.assert_awaited_once_with("https://example.com/article")


@pytest.mark.asyncio
async def test_route_direct(router, mock_search_svc, mock_extractor_svc):
    res = await router.route_and_execute("Tell me a joke about computers")
    assert res.tool_name is None
    assert res.context_text is None
    mock_search_svc.search.assert_not_awaited()
    mock_extractor_svc.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_to_search_with_event_deep_crawl(mock_search_svc, mock_extractor_svc):
    mock_search_svc.search.return_value = [
        SearchResult(title="Unstop Hackathons", url="https://unstop.com/hackathons/hyd", snippet="Top hackathons")
    ]
    mock_search_svc.format_for_llm = MagicMock(return_value="Search snippets")

    mock_crawler = AsyncMock()
    from app.services.recursive_crawler import DeepCrawlResult
    from app.schemas.entities import Hackathon

    mock_crawler.deep_crawl.return_value = DeepCrawlResult(
        seed_url="https://unstop.com/hackathons/hyd",
        seed_content=ExtractedContent(
            url="https://unstop.com/hackathons/hyd",
            title="Unstop Hackathons",
            markdown="| Event | Date | Location |\n|---|---|---|\n| TechFest 2026 | Nov 25, 2026 | Hyderabad |",
            success=True,
        ),
    )

    mock_extractor = AsyncMock()
    mock_extractor.extract_hackathons.return_value = [
        Hackathon(
            name="TechFest 2026",
            event_date="Nov 25, 2026",
            location="Hyderabad",
            source_url="https://unstop.com/hackathons/hyd",
        )
    ]
    mock_extractor.format_for_llm = MagicMock(return_value="### Verified Hackathons:\n- TechFest 2026")

    router = ToolRouter(
        search_svc=mock_search_svc,
        extractor_svc=mock_extractor_svc,
        crawler_svc=mock_crawler,
        structured_extractor=mock_extractor,
    )

    res = await router.route_and_execute("hackathons in hyd this month")
    assert res.tool_name == "searxng_search"
    assert "TechFest 2026" in res.context_text
    mock_crawler.deep_crawl.assert_awaited_once()

