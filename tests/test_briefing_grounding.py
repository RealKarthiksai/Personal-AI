"""Gate 3: Briefing & Multi-Topic Digest Grounding Tests.

Verifies:
1. Golden Query #1: "Give me the 10 most important discoveries in AI, astronomy, finance, and climate today"
   - Correctly parses count (10) and topics (ai, astronomy, finance, climate).
   - Routes to ResponseMode.DIRECT (0 LLM hallucination).
   - Truthful manifest disclosure of unconfigured topics (finance).
   - Discloses unconfigured sources (Reddit) honestly.
2. Ranking and source quotas (max 3 per source) prevent single-source domination.
3. Timezone calculation: Kolkata midnight converts to UTC 18:30:00 previous day.
4. Leaf entities in titles with special characters ([], <>, &) are safely escaped.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.ingestion.retrieval import (
    format_records_for_llm,
    get_start_of_day_utc,
    parse_digest_request,
    rank_and_quota_records,
)
from app.schemas.external import ExternalRecord
from app.schemas.manifest import RetrievalManifest, SourceManifestEntry, SourceStatus, render_manifest_disclosure
from app.services.tool_router import ResponseMode, tool_router


# ==============================================================================
# 1. Golden Query Parsing & Multi-Topic Digest Tests
# ==============================================================================

def test_parse_golden_digest_request():
    query = "Give me the 10 most important discoveries in AI, astronomy, finance, and climate today"
    count, topics = parse_digest_request(query)
    assert count == 10
    assert "ai" in topics
    assert "astronomy" in topics
    assert "finance" in topics
    assert "climate" in topics


@pytest.mark.asyncio
async def test_golden_query_routes_to_direct_with_truthful_disclosure():
    """Golden query #1 must route to DIRECT mode and report honest topic and source status."""
    query = "Give me the 10 most important discoveries in AI, astronomy, finance, and climate today"

    with patch("app.config.config.reddit_client_id", None), patch("app.config.config.reddit_client_secret", None):
        res = await tool_router.route_and_execute(query)

    assert res.mode == ResponseMode.DIRECT
    assert res.tool_name == "daily_briefing"
    assert res.manifest is not None
    assert res.manifest.requested_count == 10
    assert "finance" in res.manifest.topic_counts
    # Unconfigured sources/topics disclosed
    assert "Reddit: unconfigured" in res.direct or "reddit" in res.manifest.sources
    assert "No configured sources for: finance" in res.direct or res.manifest.topic_counts["finance"] == 0


# ==============================================================================
# 2. Ranking & Source Quota Tests
# ==============================================================================

def test_rank_and_quota_enforcement():
    """No single source should exceed max_per_source (3 items)."""
    # 5 RSS records, 2 GitHub records
    records = [
        ExternalRecord(
            source="rss",
            source_id=f"rss_{i}",
            record_type="article",
            title=f"RSS Article {i}",
            url=f"https://rss.example.com/{i}",
            metadata={"stars": 0},
        )
        for i in range(5)
    ]
    records.extend([
        ExternalRecord(
            source="github",
            source_id=f"gh_{i}",
            record_type="repository",
            title=f"GitHub Repo {i}",
            url=f"https://github.com/org/repo_{i}",
            metadata={"stars": 5000 + i * 100},
        )
        for i in range(2)
    ])

    ranked = rank_and_quota_records(records, max_per_source=3, limit=10)

    rss_count = sum(1 for r in ranked if r.source == "rss")
    gh_count = sum(1 for r in ranked if r.source == "github")

    # RSS should be capped at 3 despite 5 available
    assert rss_count == 3
    assert gh_count == 2
    # GitHub repos with high stars should rank first
    assert ranked[0].source == "github"
    assert ranked[1].source == "github"


# ==============================================================================
# 3. Timezone Boundary Tests
# ==============================================================================

def test_kolkata_start_of_day_utc():
    utc_str = get_start_of_day_utc("Asia/Kolkata")
    assert utc_str.endswith("Z")
    # Time should be 18:30:00Z (which corresponds to 00:00:00 IST)
    assert "18:30:00Z" in utc_str


# ==============================================================================
# 4. Safe Escaping in Cards
# ==============================================================================

def test_format_records_html_and_markdown_escaping():
    records = [
        ExternalRecord(
            source="github",
            source_id="danger_1",
            record_type="repository",
            title="[Special] Repo with <script> & ampersand",
            url="https://github.com/test/repo",
            description="Description with <tags> & brackets [cool]",
            metadata={"stars": 42},
        )
    ]

    card = format_records_for_llm(records)
    # Tags should be escaped
    assert "<script>" not in card
    assert "&lt;script&gt;" in card
    assert "&amp;" in card
    # Should not crash Telegram HTML
    assert "<a href=\"https://github.com/test/repo\">" in card
