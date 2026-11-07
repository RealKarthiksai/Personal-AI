"""Memory retrieval, ranking, and compact context construction for LLM prompt injection."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.memory.config import get_memory_profile
from app.memory.models import MemoryItem, MemoryTier
from app.memory.profile import format_profile_block
from app.memory.repository import (
    list_memories,
    search_memories_fts,
    touch_memory_access,
)
from app.services.query_normalizer import normalize_query
from app.utils.logging import get_logger

logger = get_logger("app.memory.retrieval")


def estimate_tokens(text: str) -> int:
    """Fast local estimate of token count (chars / 4)."""
    return max(1, len(text) // 4)


def build_memory_context(
    user_id: int,
    query: str,
    budget_tokens: Optional[int] = None,
    is_group: bool = False,
) -> str:
    """Build a compact, prioritized memory block wrapped in <user_memory_data> tags.

    Trim priority from bottom to top:
    1. Structured Profile block (never dropped unless completely empty)
    2. Core and Pinned memories
    3. FTS5 Search-relevant memories
    4. Recent daily digest
    """
    profile_cfg = get_memory_profile()
    budget = budget_tokens or profile_cfg.context_tokens

    # Group chat safety: never leak private memories in a group chat
    if is_group:
        prof_block = format_profile_block(user_id)
        if not prof_block:
            return ""
        # Only include basic identity fields in group
        safe_lines = [l for l in prof_block.splitlines() if any(k in l.lower() for k in ("name:", "language:"))]
        if not safe_lines:
            return ""
        return "<user_memory_data>\n" + "\n".join(safe_lines) + "\n</user_memory_data>"

    # 1. Profile block
    profile_text = format_profile_block(user_id)
    consumed_tokens = estimate_tokens(profile_text)

    # 2. Core & Pinned memories
    core_items = list_memories(user_id=user_id, tier=MemoryTier.CORE, limit=10)
    pinned_items = [m for m in list_memories(user_id=user_id, limit=20) if m.pinned and m.tier != MemoryTier.CORE]
    priority_items = core_items + pinned_items

    # 3. Relevant search-based memories via FTS5
    clean_query = normalize_query(query).normalized if query else ""
    fts_results = search_memories_fts(user_id=user_id, query_text=clean_query, limit=10) if clean_query else []

    # Exclude already included priority items from FTS results
    seen_ids: Set[int] = {m.id for m in priority_items if m.id is not None}
    search_items: List[MemoryItem] = []
    for m in fts_results:
        if m.id not in seen_ids:
            search_items.append(m)
            if m.id is not None:
                seen_ids.add(m.id)

    # 4. Recent daily digest if query has temporal/vague intent or budget permits
    is_vague = any(kw in query.lower() for kw in ("yesterday", "recent", "remind me", "what did i", "my notes", "remember"))
    recent_items: List[MemoryItem] = []
    if is_vague or len(search_items) < 3:
        daily_items = list_memories(user_id=user_id, tier=MemoryTier.DAILY, limit=6)
        for m in daily_items:
            if m.id not in seen_ids:
                recent_items.append(m)
                if m.id is not None:
                    seen_ids.add(m.id)

    # Assemble sections subject to token budget (trim from bottom up)
    sections: List[str] = []
    touched_ids: List[int] = []

    if profile_text:
        sections.append(profile_text)

    # Format memory lines
    priority_lines = []
    for m in priority_items:
        priority_lines.append(f"- {m.text}")
        if m.id is not None:
            touched_ids.append(m.id)

    search_lines = []
    for m in search_items:
        # Add channel provenance if known
        prov = f" [{m.source_channels[0]}, {m.period}]" if m.source_channels and m.period else ""
        search_lines.append(f"- {m.text}{prov}")
        if m.id is not None:
            touched_ids.append(m.id)

    recent_lines = []
    for m in recent_items:
        recent_lines.append(f"- ({m.period}) {m.text}")
        if m.id is not None:
            touched_ids.append(m.id)

    # Section 2: Core Facts
    if priority_lines:
        sec = "Core Facts & Preferences:\n" + "\n".join(priority_lines)
        if consumed_tokens + estimate_tokens(sec) <= budget:
            sections.append(sec)
            consumed_tokens += estimate_tokens(sec)

    # Section 3: Relevant Context
    if search_lines:
        sec = "Relevant Past Notes:\n" + "\n".join(search_lines)
        if consumed_tokens + estimate_tokens(sec) <= budget:
            sections.append(sec)
            consumed_tokens += estimate_tokens(sec)

    # Section 4: Recent Activity
    if recent_lines:
        sec = "Recent Activity:\n" + "\n".join(recent_lines)
        if consumed_tokens + estimate_tokens(sec) <= budget:
            sections.append(sec)
            consumed_tokens += estimate_tokens(sec)

    if not sections:
        return ""

    # Reinforce accessed memories
    if touched_ids:
        touch_memory_access(touched_ids)

    content = "\n\n".join(sections)
    return (
        "<user_memory_data>\n"
        f"{content}\n"
        "</user_memory_data>"
    )


def debug_context(user_id: int, query: str) -> str:
    """Return the exact raw memory context string that would be injected."""
    return build_memory_context(user_id, query)
