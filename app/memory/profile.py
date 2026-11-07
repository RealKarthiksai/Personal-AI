"""Structured profile management and conflict resolution."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.memory.models import ExtractedFact, ProfileFieldItem
from app.memory.repository import get_profile_field, list_profile_fields, save_profile_field
from app.utils.logging import get_logger

logger = get_logger("app.memory.profile")


def update_profile_from_fact(
    user_id: int,
    fact: Optional[ExtractedFact] = None,
    source_memory_id: Optional[int] = None,
    key: Optional[str] = None,
    value: Optional[str] = None,
    memory_id: Optional[int] = None,
) -> Optional[ProfileFieldItem]:
    """Update user profile attribute from an extracted fact with conflict resolution."""
    if fact is None:
        if not key or not value:
            return None
        fact = ExtractedFact(
            text=f"{key}: {value}",
            category="identity",
            importance=4,
            confidence=1.0,
            source_snippet="",
            profile_key=key,
            profile_value=value,
        )
        source_memory_id = source_memory_id or memory_id

    if not fact.profile_key or not fact.profile_value:
        return None

    key_clean = fact.profile_key.strip().lower()
    val_clean = fact.profile_value.strip()

    existing = get_profile_field(user_id, key_clean)
    if existing:
        # Never silently overwrite a user-confirmed field with an unconfirmed extraction
        if existing.confirmed and fact.confidence < 0.95:
            logger.info(
                "Profile conflict: preserved confirmed field %s for user %d",
                key_clean,
                user_id,
            )
            return existing

        # Don't update if value hasn't changed
        if str(existing.value) == val_clean:
            return existing

    field_item = ProfileFieldItem(
        user_id=user_id,
        key=key_clean,
        value=val_clean,
        confidence=fact.confidence,
        confirmed=False,
        source_memory_id=source_memory_id,
    )
    save_profile_field(field_item)
    return field_item


def get_user_profile_summary(user_id: int) -> Dict[str, Any]:
    """Retrieve full structured profile dictionary for a user."""
    fields = list_profile_fields(user_id)
    summary: Dict[str, Any] = {}
    for f in fields:
        val = f.value
        if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
            try:
                val = json.loads(val)
            except Exception:
                pass
        summary[f.key] = val
    return summary


def format_profile_block(user_id: int) -> str:
    """Format structured user profile into a concise key-value block for LLM prompt injection."""
    profile = get_user_profile_summary(user_id)
    if not profile:
        return ""

    lines: List[str] = ["User Profile:"]
    # Standard ordering for high readability
    priority_keys = ["name", "city", "timezone", "language", "current_project", "interests", "preferences"]
    for k in priority_keys:
        if k in profile and profile[k]:
            lines.append(f"- {k.replace('_', ' ').capitalize()}: {profile[k]}")

    for k, v in profile.items():
        if k not in priority_keys and v:
            lines.append(f"- {k.replace('_', ' ').capitalize()}: {v}")

    return "\n".join(lines)
