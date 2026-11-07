"""Source verification, freshness scoring, and conflict detection service.

Validates extracted events against source authority hierarchy and temporal context
to prevent hallucinated or expired events from reaching the user.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.context.temporal import get_temporal_context
from app.schemas.entities import Hackathon
from app.utils.logging import get_logger

logger = get_logger("app.source_verifier")

# Authority tiers
OFFICIAL_DOMAINS = {
    "github.com",
    "github.io",
}
OFFICIAL_SUFFIXES = (
    ".edu",
    ".edu.in",
    ".ac.in",
    ".gov",
    ".gov.in",
    ".org.in",
)

VERIFIED_PLATFORMS = {
    "devfolio.co",
    "unstop.com",
    "mlh.io",
    "hackerearth.com",
    "kaggle.com",
    "dorahacks.io",
    "hack2skill.com",
    "reskilll.com",
}

DIRECTORY_PLATFORMS = {
    "eventbrite.com",
    "eventbrite.in",
    "meetup.com",
    "lu.ma",
    "townscript.com",
    "allevents.in",
    "insider.in",
    "bookmyshow.com",
    "commudle.com",
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def get_source_authority(url: str) -> str:
    """Classify the URL into an authority tier: OFFICIAL, VERIFIED_PLATFORM, DIRECTORY, or NEWS_BLOG."""
    if not url:
        return "NEWS_BLOG"
    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower().split(":")[0]
        # Remove leading www.
        if netloc.startswith("www."):
            netloc = netloc[4:]

        if netloc in OFFICIAL_DOMAINS or netloc.endswith(".github.io") or any(netloc.endswith(sfx) for sfx in OFFICIAL_SUFFIXES):
            return "OFFICIAL"
        if any(vp in netloc for vp in VERIFIED_PLATFORMS):
            return "VERIFIED_PLATFORM"
        if any(dp in netloc for dp in DIRECTORY_PLATFORMS):
            return "DIRECTORY"
    except Exception:
        pass
    return "NEWS_BLOG"


def parse_date_components(date_str: Optional[str]) -> Optional[Tuple[int, int, Optional[int]]]:
    """Extract (year, month, day) from arbitrary date strings like 'Nov 20-22, 2026' or '2026-11-20'."""
    if not date_str:
        return None

    # Check ISO format YYYY-MM-DD
    iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if iso_match:
        return int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))

    # Look for Month Name and Year
    text_lower = date_str.lower()
    found_month = None
    for m_name, m_num in MONTH_MAP.items():
        if re.search(rf"\b{m_name}\b", text_lower):
            found_month = m_num
            break

    year_match = re.search(r"\b(202\d)\b", date_str)
    year = int(year_match.group(1)) if year_match else None

    # Look for day number
    day_match = re.search(r"\b([1-3]?\d)(?:st|nd|rd|th)?\b", date_str)
    day = int(day_match.group(1)) if day_match else None

    if found_month and year:
        return year, found_month, day
    return None


class SourceVerifier:
    """Verifies freshness, checks date consistency, and scores source confidence."""

    def __init__(self, tz_name: str = "Asia/Kolkata") -> None:
        self.tz_name = tz_name

    def check_freshness(self, date_str: Optional[str], now: Optional[datetime] = None) -> Tuple[str, bool]:
        """Determine if an event date is PAST/EXPIRED, HAPPENING_NOW, or UPCOMING.

        Returns (status_str, is_expired).
        """
        if not date_str:
            return "UNKNOWN", False

        if now is None:
            now = datetime.now(ZoneInfo(self.tz_name))

        components = parse_date_components(date_str)
        if not components:
            return "UNKNOWN", False

        year, month, day = components

        # If the year is strictly in the past
        if year < now.year:
            return "EXPIRED", True
        # If past year is in the future
        if year > now.year:
            return "UPCOMING", False

        # Same year: check month
        if month < now.month:
            return "EXPIRED", True
        if month > now.month:
            return "UPCOMING", False

        # Same month
        if day is not None:
            if day < now.day:
                return "EXPIRED", True
            if day == now.day:
                return "HAPPENING_NOW", False
            return "UPCOMING", False

        # In current month but no specific day
        return "HAPPENING_NOW", False

    def verify_and_score(
        self,
        hackathons: List[Hackathon],
        filter_expired: bool = False,
        now: Optional[datetime] = None,
    ) -> List[Hackathon]:
        """Score each hackathon, check for date conflicts across sources, and assign confidence."""
        if now is None:
            now = datetime.now(ZoneInfo(self.tz_name))

        # 1. Group by normalized name to detect conflicts
        name_groups: dict[str, List[Hackathon]] = {}
        for h in hackathons:
            norm_name = re.sub(r"[^\w\s]", "", h.name).strip().lower()
            name_groups.setdefault(norm_name, []).append(h)

        verified: List[Hackathon] = []

        for h in hackathons:
            authority = get_source_authority(h.source_url)
            event_status, event_expired = self.check_freshness(h.event_date, now)
            deadline_status, deadline_expired = self.check_freshness(h.deadline, now)

            is_expired = event_expired or (deadline_expired and not h.event_date)

            # Check conflicts across group
            norm_name = re.sub(r"[^\w\s]", "", h.name).strip().lower()
            group = name_groups.get(norm_name, [])
            has_date_conflict = False
            if len(group) > 1:
                dates = {item.event_date for item in group if item.event_date}
                if len(dates) > 1:
                    has_date_conflict = True

            # Determine confidence
            if has_date_conflict:
                confidence = "CONFLICTED"
            elif is_expired:
                confidence = "EXPIRED"
            elif authority in ("OFFICIAL", "VERIFIED_PLATFORM"):
                confidence = "HIGH"
            elif authority == "DIRECTORY":
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            h.confidence = confidence

            if filter_expired and is_expired:
                logger.info("Filtering expired hackathon: %s (%s)", h.name, h.event_date)
                continue

            verified.append(h)

        return verified
