"""Unit tests for SourceVerifier and freshness detection."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.schemas.entities import Hackathon
from app.services.source_verifier import (
    SourceVerifier,
    get_source_authority,
    parse_date_components,
)


def test_get_source_authority():
    assert get_source_authority("https://karna.github.io/hackathon") == "OFFICIAL"
    assert get_source_authority("https://events.iith.ac.in/hack") == "OFFICIAL"
    assert get_source_authority("https://devfolio.co/explore") == "VERIFIED_PLATFORM"
    assert get_source_authority("https://unstop.com/hackathons/hyderabad") == "VERIFIED_PLATFORM"
    assert get_source_authority("https://www.eventbrite.com/e/tech-event") == "DIRECTORY"
    assert get_source_authority("https://medium.com/@user/hackathons-list") == "NEWS_BLOG"


def test_parse_date_components():
    assert parse_date_components("2026-11-20") == (2026, 11, 20)
    assert parse_date_components("Nov 20-22, 2026") == (2026, 11, 20)
    assert parse_date_components("September 2026") == (2026, 9, None)
    assert parse_date_components("October 4, 2026") == (2026, 10, 4)
    assert parse_date_components("invalid string") is None


def test_check_freshness():
    verifier = SourceVerifier()
    # Anchor date: November 7, 2026
    fixed_now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    # Past events
    status, expired = verifier.check_freshness("September 2026", now=fixed_now)
    assert status == "EXPIRED" and expired is True

    status, expired = verifier.check_freshness("October 4, 2026", now=fixed_now)
    assert status == "EXPIRED" and expired is True

    status, expired = verifier.check_freshness("Nov 2, 2026", now=fixed_now)
    assert status == "EXPIRED" and expired is True

    # Current / Upcoming events
    status, expired = verifier.check_freshness("Nov 7, 2026", now=fixed_now)
    assert status == "HAPPENING_NOW" and expired is False

    status, expired = verifier.check_freshness("Nov 20-22, 2026", now=fixed_now)
    assert status == "UPCOMING" and expired is False

    status, expired = verifier.check_freshness("December 2026", now=fixed_now)
    assert status == "UPCOMING" and expired is False


def test_verify_and_score_confidence():
    verifier = SourceVerifier()
    fixed_now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    items = [
        Hackathon(
            name="Devfolio Hack 2026",
            event_date="Nov 20-22, 2026",
            source_url="https://devfolio.co/hackathon",
        ),
        Hackathon(
            name="Old CodeStorm",
            event_date="September 2026",
            source_url="https://example.com/past",
        ),
        Hackathon(
            name="Meetup Hack",
            event_date="Nov 15, 2026",
            source_url="https://meetup.com/event",
        ),
    ]

    scored = verifier.verify_and_score(items, filter_expired=False, now=fixed_now)
    assert scored[0].confidence == "HIGH"
    assert scored[1].confidence == "EXPIRED"
    assert scored[2].confidence == "MEDIUM"

    # With filter_expired=True, old event should be filtered out
    filtered = verifier.verify_and_score(items, filter_expired=True, now=fixed_now)
    assert len(filtered) == 2
    assert all(h.name != "Old CodeStorm" for h in filtered)


def test_verify_conflicted_dates():
    verifier = SourceVerifier()
    fixed_now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    items = [
        Hackathon(
            name="CyberStorm",
            event_date="Nov 20, 2026",
            source_url="https://source-a.com",
        ),
        Hackathon(
            name="CyberStorm",
            event_date="Dec 10, 2026",
            source_url="https://source-b.com",
        ),
    ]

    scored = verifier.verify_and_score(items, filter_expired=False, now=fixed_now)
    assert all(h.confidence == "CONFLICTED" for h in scored)
