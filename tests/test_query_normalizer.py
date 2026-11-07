"""Unit tests for query normalizer and expansion pipeline."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.query_normalizer import (
    detect_query_intent,
    normalize_query,
    replace_location_aliases,
)


def test_replace_location_aliases():
    # Basic replacements
    text, loc = replace_location_aliases("hackathons in hyd")
    assert text == "hackathons in Hyderabad"
    assert loc == "Hyderabad"

    # Multi-location & case insensitivity
    text2, loc2 = replace_location_aliases("travel from BLR to CHEnnai")
    assert text2 == "travel from Bengaluru to Chennai"
    assert loc2 == "Bengaluru"

    # Word boundary guard: 'hydration' and 'hydraulic' must not be replaced
    text3, loc3 = replace_location_aliases("hydration test for hydraulic system in hyd")
    assert text3 == "hydration test for hydraulic system in Hyderabad"
    assert loc3 == "Hyderabad"


def test_detect_query_intent():
    assert detect_query_intent("AI hackathons 2026") == "events"
    assert detect_query_intent("breaking news about election") == "news"
    assert detect_query_intent("research paper on diffusion models") == "research"
    assert detect_query_intent("react native api documentation") == "documentation"
    assert detect_query_intent("best coffee shops") == "general_search"


def test_normalize_query_full_pipeline():
    fixed_now = datetime(2026, 11, 7, 16, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    raw = "hackathons in hyd this month"

    result = normalize_query(raw, now=fixed_now)

    assert result.original == "hackathons in hyd this month"
    assert result.normalized == "hackathons in Hyderabad November 2026"
    assert result.detected_location == "Hyderabad"
    assert result.intent == "events"
    assert len(result.expanded_queries) >= 1
    assert any("Hyderabad November 2026" in q for q in result.expanded_queries)
