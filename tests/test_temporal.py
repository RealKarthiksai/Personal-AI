"""Unit tests for temporal context and relative date resolution."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.context.temporal import (
    build_system_temporal_prompt,
    get_next_weekday,
    get_temporal_context,
    resolve_relative_dates,
)


def test_get_temporal_context():
    ctx = get_temporal_context("Asia/Kolkata")
    assert "current_date" in ctx
    assert "current_time" in ctx
    assert ctx["timezone"] == "Asia/Kolkata"
    assert ctx["year"] == 2026
    assert ctx["month"] == "November"


def test_build_system_temporal_prompt():
    prompt = build_system_temporal_prompt("Asia/Kolkata")
    assert "CURRENT DATE AND TIME" in prompt
    assert "TEMPORAL RULES" in prompt
    assert "Asia/Kolkata" in prompt
    assert "Today refers to the current date" in prompt
    assert "November 2026" in prompt
    assert "December 2026" in prompt


def test_resolve_relative_dates_normal():
    # Fixed point: Saturday, Nov 7, 2026
    fixed_now = datetime(2026, 11, 7, 16, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

    # Test "this month"
    res, _ = resolve_relative_dates("Hackathons this month", now=fixed_now)
    assert res == "Hackathons November 2026"

    # Test "next month"
    res, _ = resolve_relative_dates("Events next month", now=fixed_now)
    assert res == "Events December 2026"

    # Test "yesterday"
    res, _ = resolve_relative_dates("What happened yesterday?", now=fixed_now)
    assert res == "What happened November 6, 2026?"

    # Test "tomorrow"
    res, _ = resolve_relative_dates("Meetings tomorrow", now=fixed_now)
    assert res == "Meetings November 8, 2026"

    # Test "next Friday" (From Saturday Nov 7 -> next Friday is Nov 13)
    res, _ = resolve_relative_dates("Events next Friday", now=fixed_now)
    assert res == "Events November 13, 2026"


def test_year_end_boundary():
    # Fixed point: Thursday, Dec 31, 2026
    dec_31 = datetime(2026, 12, 31, 23, 59, tzinfo=ZoneInfo("Asia/Kolkata"))

    res_next_month, _ = resolve_relative_dates("Conferences next month", now=dec_31)
    assert res_next_month == "Conferences January 2027"

    res_tomorrow, _ = resolve_relative_dates("Party tomorrow", now=dec_31)
    assert res_tomorrow == "Party January 1, 2027"


def test_year_start_boundary():
    # Fixed point: Friday, Jan 1, 2026
    jan_1 = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    res_last_month, _ = resolve_relative_dates("Review last month", now=jan_1)
    assert res_last_month == "Review December 2025"

    res_yesterday, _ = resolve_relative_dates("Summary yesterday", now=jan_1)
    assert res_yesterday == "Summary December 31, 2025"
