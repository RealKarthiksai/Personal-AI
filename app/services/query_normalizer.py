"""Query normalization and expansion pipeline.

Preprocesses search queries to resolve whole-word location abbreviations,
resolve relative dates (today, this month, etc.), detect query intent,
and generate high-yield search variations without altering the user's intended meaning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.context.temporal import resolve_relative_dates

# Location aliases mapping abbreviation/alias to canonical name.
LOCATION_ALIASES: Dict[str, str] = {
    "hyd": "Hyderabad",
    "blr": "Bengaluru",
    "bangalore": "Bengaluru",
    "vizag": "Visakhapatnam",
    "chennai": "Chennai",
    "delhi": "Delhi",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "kolkata": "Kolkata",
    "ncr": "Delhi NCR",
    "sf": "San Francisco",
    "nyc": "New York City",
}


@dataclass
class NormalizedQuery:
    original: str
    normalized: str
    intent: str
    expanded_queries: List[str] = field(default_factory=list)
    detected_location: Optional[str] = None
    resolved_dates: Dict[str, str] = field(default_factory=dict)
    intent_keywords: List[str] = field(default_factory=list)



def replace_location_aliases(text: str) -> tuple[str, Optional[str]]:
    """Replace whole-word location aliases.

    Uses word boundaries (\\b) to avoid corrupting words like 'hydration'.
    Returns (cleaned_text, primary_detected_location).
    """
    detected_loc: Optional[str] = None
    result = text

    for alias, canonical in LOCATION_ALIASES.items():
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        if pattern.search(result):
            if not detected_loc:
                detected_loc = canonical
            result = pattern.sub(canonical, result)

    return result, detected_loc


def detect_query_intent(text: str) -> str:
    """Classify user search intent into categories."""
    lower = text.lower()
    if any(k in lower for k in ["hackathon", "hackathons", "meetup", "conference", "event", "summit", "workshop"]):
        return "events"
    if any(k in lower for k in ["news", "breaking", "headline", "happened"]):
        return "news"
    if any(k in lower for k in ["paper", "arxiv", "research", "study", "dataset"]):
        return "research"
    if any(k in lower for k in ["docs", "documentation", "api", "tutorial", "sdk", "library"]):
        return "documentation"
    return "general_search"


def normalize_query(
    raw_query: str,
    now: Optional[datetime] = None,
    tz_name: str = "Asia/Kolkata",
) -> NormalizedQuery:
    """Normalize raw user search query through abbreviation and date resolution."""
    clean = " ".join(raw_query.strip().split())

    # 1. Expand location aliases
    with_locations, loc = replace_location_aliases(clean)

    # 2. Resolve relative dates
    with_dates, date_map = resolve_relative_dates(with_locations, now=now, tz_name=tz_name)

    # 3. Detect intent
    intent = detect_query_intent(with_dates)

    # 4. Generate expanded query variations
    expanded = expand_search_queries(
        original=clean,
        normalized=with_dates,
        intent=intent,
        location=loc,
        resolved_dates=date_map,
    )

    # 5. Extract core keywords for downstream link ranking and scraping
    stop_words = {"the", "and", "for", "with", "all", "out", "about", "can", "you", "tell", "show"}
    raw_tokens = re.split(r"\W+", with_dates.lower())
    intent_keywords = [t for t in raw_tokens if len(t) > 2 and t not in stop_words]

    return NormalizedQuery(
        original=clean,
        normalized=with_dates,
        intent=intent,
        expanded_queries=expanded,
        detected_location=loc,
        resolved_dates=date_map,
        intent_keywords=intent_keywords,
    )



def expand_search_queries(
    original: str,
    normalized: str,
    intent: str,
    location: Optional[str],
    resolved_dates: Dict[str, str],
) -> List[str]:
    """Generate focused, high-yield search variations alongside the normalized query."""
    queries: List[str] = []

    # Always ensure normalized is first
    if normalized != original:
        queries.append(normalized)

    # Event specific expansions
    if intent == "events":
        time_part = " ".join(resolved_dates.values())
        loc_part = location or ""

        # Variation 1: Add AI/tech context if not already present
        if "ai" not in normalized.lower() and "tech" not in normalized.lower():
            variation_1 = f"AI and technology {normalized}".strip()
            queries.append(variation_1)

        # Variation 2: Add registration / competitions keywords
        if "registration" not in normalized.lower():
            if loc_part and time_part:
                queries.append(f"hackathons competitions {loc_part} {time_part}".strip())
                queries.append(f"hackathon registration {loc_part} {time_part}".strip())
            else:
                queries.append(f"{normalized} registration".strip())

    elif intent == "news":
        queries.append(f"latest news {normalized}")

    # Remove duplicates while preserving order
    seen = {original.lower()}
    final_expanded: List[str] = []
    for q in queries:
        cleaned_q = " ".join(q.split())
        if cleaned_q.lower() not in seen:
            seen.add(cleaned_q.lower())
            final_expanded.append(cleaned_q)

    return final_expanded
