"""Tests for memory retrieval, token budgeting, and context injection formatting."""

from __future__ import annotations

import pytest

from app.database import database
from app.memory.identity import resolve_user_id
from app.memory.models import MemoryItem, MemoryTier
from app.memory.profile import update_profile_from_fact
from app.memory.repository import list_memories, save_memory
from app.memory.retrieval import build_memory_context, estimate_tokens


@pytest.fixture(autouse=True)
def init_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_karna.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    database._init_lock = False
    database.init_db()
    yield test_db


def test_build_memory_context_structure():
    uid = resolve_user_id("telegram", "test_retrieval_user")

    # Set up profile fields
    update_profile_from_fact(user_id=uid, key="name", value="Clark Kent")
    update_profile_from_fact(user_id=uid, key="city", value="Metropolis")
    update_profile_from_fact(user_id=uid, key="language", value="English")

    # Set up core fact
    save_memory(
        MemoryItem(
            id=None,
            user_id=uid,
            tier=MemoryTier.CORE,
            period="2026-11-01",
            text="User works as an investigative reporter at Daily Planet",
            importance=5,
        )
    )

    # Set up daily fact
    save_memory(
        MemoryItem(
            id=None,
            user_id=uid,
            tier=MemoryTier.DAILY,
            period="2026-11-07",
            text="User investigated LexCorp financial records yesterday",
            importance=3,
            source_channels=["telegram"],
        )
    )

    context = build_memory_context(user_id=uid, query="What did I investigate yesterday?")
    assert "<user_memory_data>" in context
    assert "</user_memory_data>" in context
    assert "Clark Kent" in context
    assert "Metropolis" in context
    assert "Daily Planet" in context
    assert "LexCorp" in context


def test_build_memory_context_budget_trimming():
    uid = resolve_user_id("telegram", "test_budget_user")

    update_profile_from_fact(user_id=uid, key="name", value="Bruce")

    # Save multiple items
    for i in range(10):
        save_memory(
            MemoryItem(
                id=None,
                user_id=uid,
                tier=MemoryTier.DAILY,
                period="2026-11-01",
                text=f"Note entry number {i} with detailed text about various activities and tasks",
                importance=2,
            )
        )

    # With a small token budget (30 tokens), only profile fits
    tiny_context = build_memory_context(user_id=uid, query="notes", budget_tokens=30)
    assert "User Profile:" in tiny_context
    assert "Bruce" in tiny_context
    # Low-priority entries were trimmed
    assert estimate_tokens(tiny_context) <= 40


def test_touch_memory_access_on_retrieval():
    uid = resolve_user_id("telegram", "test_touch_user")

    mem_id = save_memory(
        MemoryItem(
            id=None,
            user_id=uid,
            tier=MemoryTier.CORE,
            period="2026-11-01",
            text="User is allergic to peanuts",
            importance=5,
            access_count=0,
        )
    )

    # Retrieve context
    ctx = build_memory_context(user_id=uid, query="peanuts")
    assert "allergic to peanuts" in ctx

    # Check access_count incremented
    mems = list_memories(user_id=uid)
    peanut_mem = [m for m in mems if m.id == mem_id][0]
    assert peanut_mem.access_count == 1
    assert peanut_mem.last_accessed_at is not None


def test_group_chat_privacy_masking():
    uid = resolve_user_id("telegram", "test_group_user")

    update_profile_from_fact(user_id=uid, key="name", value="Diana")
    update_profile_from_fact(user_id=uid, key="language", value="Greek")

    save_memory(
        MemoryItem(
            id=None,
            user_id=uid,
            tier=MemoryTier.CORE,
            period="2026-11-01",
            text="Confidential: God of War is plotting against Themyscira",
            importance=5,
        )
    )

    # In a group chat, confidential memories must NOT leak
    group_ctx = build_memory_context(user_id=uid, query="hello", is_group=True)
    assert "Diana" in group_ctx
    assert "Confidential" not in group_ctx
    assert "Themyscira" not in group_ctx
