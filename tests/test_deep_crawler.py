"""Unit tests for deep link extraction and recursive crawler."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from app.database.models import ExtractedContent
from app.services.recursive_crawler import (
    RecursiveCrawler,
    extract_links,
    rank_discovered_links,
    table_to_markdown,
)


def test_extract_links():
    html = """
    <div>
        <a href="/events/ai-hackathon">AI Hackathon</a>
        <a href="https://example.com/details">Details</a>
        <a href="javascript:void(0)">Ignore me</a>
        <a href="mailto:admin@example.com">Email</a>
        <a href="/events/ai-hackathon#overview">Duplicate Anchor</a>
    </div>
    """
    links = extract_links(html, "https://example.com/discover")
    urls = [l["url"] for l in links]
    assert "https://example.com/events/ai-hackathon" in urls
    assert "https://example.com/details" in urls
    assert not any("javascript" in u for u in urls)
    assert not any("mailto" in u for u in urls)
    # Deduplication check
    assert len(urls) == 2


def test_rank_discovered_links():
    links = [
        {"url": "https://example.com/privacy-policy", "text": "Privacy Policy"},
        {"url": "https://example.com/hackathons/hyd-2026", "text": "Hyderabad Hackathon 2026"},
        {"url": "https://twitter.com/example", "text": "Twitter"},
        {"url": "https://example.com/events/ai-challenge", "text": "AI Challenge Register"},
    ]
    ranked = rank_discovered_links(links, base_url="https://example.com/all", max_links=2)
    assert len(ranked) == 2
    top_urls = [r["url"] for r in ranked]
    assert "https://example.com/hackathons/hyd-2026" in top_urls
    assert "https://example.com/events/ai-challenge" in top_urls
    assert "https://example.com/privacy-policy" not in top_urls


def test_table_to_markdown():
    html = """
    <table>
      <tr><th>Name</th><th>Date</th><th>Prize</th></tr>
      <tr><td>CodeStorm</td><td>Nov 20</td><td>$5,000</td></tr>
      <tr><td>Hack4Hyd</td><td>Nov 28</td><td>$2,500</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    md = table_to_markdown(soup.find("table"))
    assert "| Name | Date | Prize |" in md
    assert "| CodeStorm | Nov 20 | $5,000 |" in md
    assert "| Hack4Hyd | Nov 28 | $2,500 |" in md


@pytest.mark.asyncio
async def test_deep_crawl_flow():
    mock_extractor = AsyncMock()

    seed_html = """
    <html>
        <body>
            <h1>Upcoming Tech Events</h1>
            <a href="/hackathon-1">AI Hackathon Hyderabad</a>
            <a href="/privacy">Privacy</a>
        </body>
    </html>
    """
    mock_extractor.extract.side_effect = [
        ExtractedContent(
            url="https://example.com/events",
            title="Events Directory",
            markdown="Upcoming Tech Events",
            success=True,
            raw_html=seed_html,
        ),
        ExtractedContent(
            url="https://example.com/hackathon-1",
            title="AI Hackathon Hyderabad",
            markdown="Details: Held on Nov 25 at GNI Campus.",
            success=True,
        ),
    ]

    crawler = RecursiveCrawler(extractor=mock_extractor, max_child_pages=2)
    res = await crawler.deep_crawl("https://example.com/events")

    assert res.seed_url == "https://example.com/events"
    assert res.seed_content.title == "Events Directory"
    assert len(res.child_pages) == 1
    assert res.child_pages[0].title == "AI Hackathon Hyderabad"
