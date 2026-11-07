"""Tests for memory tiers, decay logic, score calculation, and online backup."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.database import database
from app.memory.decay import (
    backup_database_online,
    cleanup_expired_raw_messages,
    compute_effective_score,
    consolidate_items_extractive,
    run_tier_decay_for_user,
)
from app.memory.identity import resolve_user_id
from app.memory.models import MemoryItem, MemorySource, MemoryTier
from app.memory.repository import hard_delete_memory, list_memories, save_memory


@pytest.fixture(autouse=True)
def init_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_karna.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    database._init_lock = False
    database.init_db()
    yield test_db


def test_effective_score_calculation():
    now = datetime.now(timezone.utc)
    item = MemoryItem(
        id=1,
        user_id=1,
        tier=MemoryTier.DAILY,
        period="2026-11-01",
        text="User likes hiking",
        importance=3,
        access_count=5,
        created_at=(now - timedelta(days=2)).isoformat(),
    )
    score = compute_effective_score(item, current_time=now)
    assert score > 3.0  # Boosted by access count

    # Core items have infinite score
    item.pinned = True
    assert compute_effective_score(item, current_time=now) == 999.0

    item.pinned = False
    item.tier = MemoryTier.CORE
    assert compute_effective_score(item, current_time=now) == 999.0


def test_extractive_deduplication():
    item1 = MemoryItem(
        id=1,
        user_id=1,
        tier=MemoryTier.DAILY,
        period="2026-11-01",
        text="User prefers python 3.12 for all projects",
        importance=4,
        category="preference",
        source_message_ids=[101],
    )
    item2 = MemoryItem(
        id=2,
        user_id=1,
        tier=MemoryTier.DAILY,
        period="2026-11-02",
        text="User prefers python 3.12 for python projects",
        importance=3,
        category="preference",
        source_message_ids=[102],
    )
    deduped = consolidate_items_extractive([item1, item2])
    assert len(deduped) == 1
    assert deduped[0].id == 1
    assert set(deduped[0].source_message_ids) == {101, 102}


def test_tier_decay_daily_to_weekly_and_drop():
    now = datetime.now(timezone.utc)
    uid = resolve_user_id("telegram", "test_decay_user")

    # Item 1: High importance (4), age 8 days -> Should promote to WEEKLY
    item_important = MemoryItem(
        id=None,
        user_id=uid,
        tier=MemoryTier.DAILY,
        period="2026-11-01",
        text="User is moving to Berlin in December",
        importance=4,
        confidence=1.0,
        category="project",
        created_at=(now - timedelta(days=8)).isoformat(),
    )
    save_memory(item_important)

    # Item 2: Low importance (1), age 8 days -> Should be dropped
    item_trivial = MemoryItem(
        id=None,
        user_id=uid,
        tier=MemoryTier.DAILY,
        period="2026-11-01",
        text="User ate a sandwich today",
        importance=1,
        confidence=1.0,
        category="general",
        created_at=(now - timedelta(days=8)).isoformat(),
    )
    save_memory(item_trivial)

    # Item 3: Low importance (1), but fresh (age 2 days) -> Should be retained
    item_fresh = MemoryItem(
        id=None,
        user_id=uid,
        tier=MemoryTier.DAILY,
        period="2026-11-06",
        text="User bought milk",
        importance=1,
        confidence=1.0,
        category="general",
        created_at=(now - timedelta(days=2)).isoformat(),
    )
    save_memory(item_fresh)

    stats = run_tier_decay_for_user(uid, current_time=now)
    assert stats["promoted_weekly"] == 1
    assert stats["dropped"] == 1
    assert stats["retained"] == 1

    remaining = list_memories(user_id=uid)
    assert len(remaining) == 2
    tiers = {m.text: m.tier for m in remaining}
    assert tiers["User is moving to Berlin in December"] == MemoryTier.WEEKLY
    assert tiers["User bought milk"] == MemoryTier.DAILY


def test_core_and_pinned_immunity_to_decay():
    now = datetime.now(timezone.utc)
    uid = resolve_user_id("telegram", "test_immune_user")

    # Item 1: Core tier, age 400 days, low access
    mem_core = MemoryItem(
        id=None,
        user_id=uid,
        tier=MemoryTier.CORE,
        period="2025-01-01",
        text="User name is Alice",
        importance=5,
        created_at=(now - timedelta(days=400)).isoformat(),
    )
    save_memory(mem_core)

    # Item 2: Pinned item in Daily tier, age 100 days
    mem_pinned = MemoryItem(
        id=None,
        user_id=uid,
        tier=MemoryTier.DAILY,
        period="2026-08-01",
        text="Critical server IP is 10.0.0.1",
        importance=2,
        pinned=True,
        created_at=(now - timedelta(days=100)).isoformat(),
    )
    save_memory(mem_pinned)

    stats = run_tier_decay_for_user(uid, current_time=now)
    assert stats["dropped"] == 0
    assert stats["retained"] == 2

    remaining = list_memories(user_id=uid)
    assert len(remaining) == 2


def test_online_backup(tmp_path):
    backup_dir = str(tmp_path / "backups")
    backup_path = backup_database_online(backup_dir=backup_dir, max_backups=3)
    assert backup_path is not None
    assert os.path.exists(backup_path)
    assert os.path.getsize(backup_path) > 0


def test_cleanup_expired_raw_messages():
    now = datetime.now(timezone.utc)
    with database.transaction() as conn:
        # 1. Processed message, 5 days old -> Should delete
        conn.execute(
            """
            INSERT INTO messages (sender_id, direction, text, created_at, memory_processed_at, status)
            VALUES ('s1', 'inbound', 'old processed message', ?, ?, 'received')
            """,
            (
                (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        # 2. Unprocessed message, 5 days old -> MUST NOT delete
        conn.execute(
            """
            INSERT INTO messages (sender_id, direction, text, created_at, memory_processed_at, status)
            VALUES ('s1', 'inbound', 'old unprocessed message', ?, NULL, 'received')
            """,
            ((now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
        )
        # 3. Processed message, 1 day old -> MUST NOT delete (retention is 2 days)
        conn.execute(
            """
            INSERT INTO messages (sender_id, direction, text, created_at, memory_processed_at, status)
            VALUES ('s1', 'inbound', 'recent processed message', ?, ?, 'received')
            """,
            (
                (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )

    deleted = cleanup_expired_raw_messages(retention_days=2)
    assert deleted == 1

    with database.transaction() as conn:
        remaining = conn.execute("SELECT text FROM messages").fetchall()
        texts = [r["text"] for r in remaining]
        assert "old processed message" not in texts
        assert "old unprocessed message" in texts
        assert "recent processed message" in texts
