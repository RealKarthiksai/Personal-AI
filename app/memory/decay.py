"""Time-decay, tier consolidation, and SQLite backup engine."""

from __future__ import annotations

import math
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import config
from app.database.database import get_connection, transaction
from app.memory.config import get_memory_profile
from app.memory.models import MemoryItem, MemorySource, MemoryTier
from app.memory.repository import hard_delete_memory, list_memories, save_memory
from app.utils.logging import get_logger

logger = get_logger("app.memory.decay")


def compute_effective_score(
    memory: MemoryItem,
    current_time: Optional[datetime] = None,
    w_access: float = 0.5,
    w_age: float = 0.05,
) -> float:
    """Compute reinforcement-adjusted effective score.

    formula: effective = importance + w_access * log1p(access_count) - w_age * age_days
    Core and pinned memories are effectively infinite.
    """
    if memory.pinned or memory.importance >= 5 or memory.tier == MemoryTier.CORE or memory.source == MemorySource.EXPLICIT:
        return 999.0

    now = current_time or datetime.now(timezone.utc)
    created_dt = now
    if memory.created_at:
        try:
            created_dt = datetime.fromisoformat(memory.created_at.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    age_days = max(0.0, (now - created_dt).total_seconds() / 86400.0)
    reinforcement = w_access * math.log1p(memory.access_count)
    decay = w_age * age_days

    return float(memory.importance) + reinforcement - decay


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute token Jaccard similarity between two texts."""
    tokens_a = set(re_tokenize(text_a))
    tokens_b = set(re_tokenize(text_b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def re_tokenize(text: str) -> List[str]:
    """Helper tokenizer for similarity checks."""
    import re
    return re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower())


def consolidate_items_extractive(
    items: List[MemoryItem],
    similarity_threshold: float = 0.65,
) -> List[MemoryItem]:
    """Extractive deduplication: groups near-duplicates and retains the highest effective score fact."""
    if not items:
        return []

    # Sort items descending by effective score
    scored_items = sorted(items, key=lambda m: compute_effective_score(m), reverse=True)
    kept: List[MemoryItem] = []

    for candidate in scored_items:
        is_duplicate = False
        for chosen in kept:
            # Check within the same category
            if candidate.category == chosen.category:
                sim = jaccard_similarity(candidate.text, chosen.text)
                if sim >= similarity_threshold:
                    is_duplicate = True
                    # Combine source message IDs and channels
                    chosen.source_message_ids = list(set(chosen.source_message_ids + candidate.source_message_ids))
                    chosen.source_channels = list(set(chosen.source_channels + candidate.source_channels))
                    break
        if not is_duplicate:
            kept.append(candidate)

    return kept


def run_tier_decay_for_user(
    user_id: int,
    current_time: Optional[datetime] = None,
) -> Dict[str, int]:
    """Execute tier decay for user: daily -> weekly -> monthly -> drop."""
    now = current_time or datetime.now(timezone.utc)
    profile = get_memory_profile()

    memories = list_memories(user_id=user_id, limit=500)
    stats = {"promoted_weekly": 0, "promoted_monthly": 0, "dropped": 0, "retained": 0}

    # Minimum effective scores for tier survival
    # daily -> 2, weekly -> 3, monthly -> 4
    tier_thresholds = {
        MemoryTier.DAILY: 1.5,
        MemoryTier.WEEKLY: 2.0,
        MemoryTier.MONTHLY: 2.5,
        MemoryTier.YEARLY: 3.0,
    }

    for mem in memories:
        if mem.tier == MemoryTier.CORE or mem.pinned or mem.importance >= 5 or mem.source == MemorySource.EXPLICIT:
            # Promote to CORE tier if not already
            if mem.tier != MemoryTier.CORE:
                mem.tier = MemoryTier.CORE
                save_memory(mem)
            stats["retained"] += 1
            continue

        score = compute_effective_score(mem, current_time=now)
        min_score = tier_thresholds.get(mem.tier, 2.0)

        # Check age
        created_dt = now
        if mem.created_at:
            try:
                created_dt = datetime.fromisoformat(mem.created_at.replace("Z", "+00:00"))
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        age_days = (now - created_dt).total_seconds() / 86400.0

        if mem.tier == MemoryTier.DAILY:
            if age_days >= 7.0:
                if score >= tier_thresholds[MemoryTier.WEEKLY]:
                    mem.tier = MemoryTier.WEEKLY
                    save_memory(mem)
                    stats["promoted_weekly"] += 1
                else:
                    hard_delete_memory(user_id=user_id, memory_id=mem.id)  # type: ignore
                    stats["dropped"] += 1
            else:
                stats["retained"] += 1

        elif mem.tier == MemoryTier.WEEKLY:
            if age_days >= 30.0:
                if score >= tier_thresholds[MemoryTier.MONTHLY]:
                    mem.tier = MemoryTier.MONTHLY
                    save_memory(mem)
                    stats["promoted_monthly"] += 1
                else:
                    hard_delete_memory(user_id=user_id, memory_id=mem.id)  # type: ignore
                    stats["dropped"] += 1
            else:
                stats["retained"] += 1

        elif mem.tier == MemoryTier.MONTHLY:
            if age_days >= 365.0:
                if score >= tier_thresholds[MemoryTier.YEARLY]:
                    mem.tier = MemoryTier.YEARLY
                    save_memory(mem)
                else:
                    hard_delete_memory(user_id=user_id, memory_id=mem.id)  # type: ignore
                    stats["dropped"] += 1
            else:
                stats["retained"] += 1

    return stats


def backup_database_online(backup_dir: str = "data/backups", max_backups: int = 7) -> Optional[str]:
    """Execute live online SQLite backup using backup API and retain last max_backups."""
    try:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"chatbot_backup_{timestamp_str}.db")

        source_conn = get_connection()
        dest_conn = sqlite3.connect(backup_path)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

        # Prune old backups
        files = sorted([
            os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
            if f.startswith("chatbot_backup_") and f.endswith(".db")
        ])
        while len(files) > max_backups:
            oldest = files.pop(0)
            try:
                os.remove(oldest)
            except Exception:
                pass

        logger.info("Created online database backup: %s", backup_path)
        return backup_path
    except Exception as e:
        logger.error("Failed to perform online database backup: %s", e)
        return None


def cleanup_expired_raw_messages(retention_days: int = 2) -> int:
    """Delete raw message text older than retention_days ONLY if memory_processed_at is set."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        cur = conn.execute(
            """
            DELETE FROM messages
            WHERE memory_processed_at IS NOT NULL
              AND created_at < ?
            """,
            (cutoff,),
        )
        count = cur.rowcount
        if count > 0:
            logger.info("Cleaned up %d expired processed raw messages", count)
        return count
