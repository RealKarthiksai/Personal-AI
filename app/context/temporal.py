"""Temporal context provider and relative date resolver.

Dynamically computes local date, time, and timezone information, formats
strict temporal instructions for the LLM, and deterministically resolves
relative date expressions (today, tomorrow, this month, next month, next Friday, etc.).
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo


def get_temporal_context(tz_name: str = "Asia/Kolkata") -> dict:
    """Return live temporal metadata for the configured timezone."""
    now = datetime.now(ZoneInfo(tz_name))
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S"),
        "timezone": tz_name,
        "day": now.strftime("%A"),
        "month": now.strftime("%B"),
        "year": now.year,
        "iso_datetime": now.isoformat(),
        "_datetime": now,
    }


def build_system_temporal_prompt(tz_name: str = "Asia/Kolkata") -> str:
    """Format standard temporal instructions to inject into LLM system prompts."""
    ctx = get_temporal_context(tz_name)
    now: datetime = ctx["_datetime"]

    # Calculate next month for clarity in rules
    next_month_num = now.month + 1 if now.month < 12 else 1
    next_month_year = now.year if now.month < 12 else now.year + 1
    next_month_name = calendar.month_name[next_month_num]

    return (
        f"[CURRENT DATE AND TIME - INTERNAL REFERENCE (Do not output as message header)]\n\n"
        f"Date: {ctx['current_date']} ({ctx['day']})\n"
        f"Time: {now.strftime('%H:%M')}\n"
        f"Timezone: {ctx['timezone']}\n\n"
        f"TEMPORAL RULES\n\n"
        f"- Today refers to the current date ({ctx['current_date']}).\n"
        f"- This month refers to the current calendar month ({ctx['month']} {ctx['year']}).\n"
        f"- Next month refers to the following calendar month ({next_month_name} {next_month_year}).\n"
        f"- Past events must not be presented as upcoming.\n"
        f"- Do not output current date/time headers or cards unless the user specifically asks for the time or date."
    )


def get_next_weekday(now: datetime, target_weekday: int) -> datetime:
    """Return the date of the next occurrence of target_weekday (0=Monday, 4=Friday, 6=Sunday)."""
    days_ahead = target_weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return now + timedelta(days=days_ahead)


def resolve_relative_dates(
    text: str,
    now: Optional[datetime] = None,
    tz_name: str = "Asia/Kolkata",
) -> Tuple[str, Dict[str, str]]:
    """Deterministically resolve relative date expressions in text.

    Returns:
        (resolved_text, mapping_of_resolved_expressions)
    """
    if now is None:
        now = datetime.now(ZoneInfo(tz_name))

    resolved_map: Dict[str, str] = {}
    modified = text

    # Compute targets
    today_str = now.strftime("%B %-d, %Y") if hasattr(now, "strftime") else now.strftime("%B %d, %Y")
    tomorrow = now + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%B %-d, %Y") if hasattr(tomorrow, "strftime") else tomorrow.strftime("%B %d, %Y")
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%B %-d, %Y") if hasattr(yesterday, "strftime") else yesterday.strftime("%B %d, %Y")

    # Months
    this_month_str = f"{now.strftime('%B')} {now.year}"

    next_month_num = now.month + 1 if now.month < 12 else 1
    next_month_year = now.year if now.month < 12 else now.year + 1
    next_month_str = f"{calendar.month_name[next_month_num]} {next_month_year}"

    last_month_num = now.month - 1 if now.month > 1 else 12
    last_month_year = now.year if now.month > 1 else now.year - 1
    last_month_str = f"{calendar.month_name[last_month_num]} {last_month_year}"

    # Next Friday
    next_friday = get_next_weekday(now, 4)  # 4 = Friday
    next_friday_str = next_friday.strftime("%B %-d, %Y") if hasattr(next_friday, "strftime") else next_friday.strftime("%B %d, %Y")

    # Ordered patterns to prevent partial shadowing
    rules = [
        (r"\bthis\s+month\b", this_month_str),
        (r"\bnext\s+month\b", next_month_str),
        (r"\blast\s+month\b", last_month_str),
        (r"\bnext\s+friday\b", next_friday_str),
        (r"\byesterday\b", yesterday_str),
        (r"\btomorrow\b", tomorrow_str),
        (r"\btoday\b", today_str),
    ]

    for pattern, replacement in rules:
        if re.search(pattern, modified, re.IGNORECASE):
            resolved_map[pattern] = replacement
            modified = re.sub(pattern, replacement, modified, flags=re.IGNORECASE)

    return modified, resolved_map
