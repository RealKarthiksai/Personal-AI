"""Unit tests for RSS and Atom feeds integration."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.database import database
from app.integrations.rss.client import RSSClient, rss_client, strip_html_tags
from app.integrations.rss.service import RSSService, struct_time_to_iso
from app.main import app

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AI News and Updates</title>
    <link>https://example.com/feed</link>
    <description>Latest in open source AI</description>
    <item>
      <title>Quantizing Qwen 3.5 for Edge Devices</title>
      <link>https://example.com/posts/qwen-edge</link>
      <guid>https://example.com/posts/qwen-edge</guid>
      <description>&lt;p&gt;A practical guide to 2-bit and 4-bit quantization.&lt;/p&gt;</description>
      <pubDate>Fri, 06 Nov 2026 12:00:00 GMT</pubDate>
      <category>ai</category>
      <category>quantization</category>
    </item>
    <item>
      <title>FastAPI and Local LLM Architectures</title>
      <link>https://example.com/posts/fastapi-llm</link>
      <guid>https://example.com/posts/fastapi-llm</guid>
      <description>Building high throughput local AI pipelines.</description>
      <pubDate>Sat, 07 Nov 2026 09:30:00 GMT</pubDate>
      <category>architecture</category>
    </item>
  </channel>
</rss>
"""


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """Provide a fresh SQLite database for each test."""
    db_file = tmp_path / "test_rss.db"
    import app.config as cfg_module

    orig_url = cfg_module.config.database_url
    cfg_module.config.database_url = f"sqlite:///{db_file}"
    database._init_lock = False
    database.init_db()
    yield
    cfg_module.config.database_url = orig_url


def test_strip_html_tags() -> None:
    assert strip_html_tags("<p>Hello <b>World</b></p>") == "Hello World"
    assert strip_html_tags("No tags here") == "No tags here"
    assert strip_html_tags(None) is None
    assert strip_html_tags("") is None


def test_resolve_feed_url() -> None:
    client = RSSClient(rsshub_base="https://custom.rsshub.io")
    assert client.resolve_feed_url("https://example.com/rss.xml") == "https://example.com/rss.xml"
    assert client.resolve_feed_url("rsshub://github/repos/new") == "https://custom.rsshub.io/github/repos/new"
    assert client.resolve_feed_url("/twitter/user/karpathy") == "https://custom.rsshub.io/twitter/user/karpathy"


def test_struct_time_to_iso() -> None:
    st = time.gmtime(1794000000)
    iso = struct_time_to_iso(st)
    assert iso is not None
    assert "2026" in iso
    assert struct_time_to_iso(None) is None


def test_subscription_lifecycle() -> None:
    service = RSSService()
    # 1. Subscribe
    sub = service.subscribe_feed("https://example.com/feed.xml", title="Example Feed", category="tech")
    assert sub["created"] is True
    assert sub["title"] == "Example Feed"

    # 2. List
    subs = service.list_subscriptions()
    assert len(subs) == 1
    assert subs[0]["url"] == "https://example.com/feed.xml"

    # 3. Duplicate subscribe (idempotent / updates title)
    sub2 = service.subscribe_feed("https://example.com/feed.xml", title="Example Feed Renamed")
    assert sub2["created"] is False
    assert sub2["title"] == "Example Feed Renamed"

    # 4. Unsubscribe
    unsub = service.unsubscribe_feed("https://example.com/feed.xml")
    assert unsub is True

    # 5. List enabled only
    enabled_subs = service.list_subscriptions(enabled_only=True)
    assert len(enabled_subs) == 0


def test_map_entry_to_record() -> None:
    service = RSSService()
    entry = {
        "id": "post-101",
        "title": "<b>Breakthrough in Local Reasoning</b>",
        "link": "https://example.com/post-101",
        "summary": "<p>Deep Dive into small reasoning models.</p>",
        "published_parsed": time.gmtime(1794000000),
        "author": "Dr. AI",
        "tags": [{"term": "reasoning"}, {"term": "benchmark"}],
    }

    record = service.map_entry_to_record("https://example.com/rss", "AI Digest", entry, feed_category="ai")
    assert record.source == "rss"
    assert record.record_type == "article"
    assert record.title == "Breakthrough in Local Reasoning"
    assert record.description == "Deep Dive into small reasoning models."
    assert record.url == "https://example.com/post-101"
    assert "reasoning" in record.metadata["tags"]
    assert record.metadata["feed_title"] == "AI Digest"
    assert record.metadata["author"] == "Dr. AI"


@pytest.mark.asyncio
async def test_sync_feed_mocked() -> None:
    mock_client = AsyncMock(spec=RSSClient)
    parsed = rss_client.parse_raw_xml(SAMPLE_RSS_XML)
    mock_client.resolve_feed_url.side_effect = lambda u: u
    mock_client.fetch_feed.return_value = parsed

    service = RSSService(client=mock_client)
    res = await service.sync_feed("https://example.com/feed")
    assert res.total_received == 2
    assert res.inserted == 2
    assert res.updated == 0

    # Idempotent re-sync
    res_again = await service.sync_feed("https://example.com/feed")
    assert res_again.inserted == 0
    assert res_again.skipped_identical == 2


def test_api_routes_with_mocks() -> None:
    client = TestClient(app)

    # 1. Subscribe
    resp = client.post(
        "/api/integrations/rss/subscribe",
        json={"url": "https://hnrss.org/frontpage", "title": "Hacker News", "category": "tech"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Hacker News"

    # 2. List
    resp = client.get("/api/integrations/rss/subscriptions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://hnrss.org/frontpage"

    # 3. Preview endpoint
    with patch("app.integrations.rss.routes.rss_client.fetch_feed", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = rss_client.parse_raw_xml(SAMPLE_RSS_XML)
        resp = client.get("/api/integrations/rss/preview?url=https://example.com/feed&limit=2")
        assert resp.status_code == 200
        preview = resp.json()
        assert preview["count"] == 2
        assert preview["entries"][0]["title"] == "Quantizing Qwen 3.5 for Edge Devices"

    # 4. Sync endpoint with mock
    with patch("app.integrations.rss.service.rss_client.fetch_feed", new_callable=AsyncMock) as mock_fetch_sync:
        mock_fetch_sync.return_value = rss_client.parse_raw_xml(SAMPLE_RSS_XML)
        resp = client.post("/api/integrations/rss/sync", json={"url": "https://hnrss.org/frontpage"})
        assert resp.status_code == 200
        sync_data = resp.json()
        assert sync_data["result"]["inserted"] == 2
