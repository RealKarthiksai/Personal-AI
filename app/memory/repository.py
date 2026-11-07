"""SQLite data access layer for long-term memory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database.database import transaction
from app.memory.models import (
    FactCategory,
    MemoryItem,
    MemorySource,
    MemoryTier,
    ProfileFieldItem,
)
from app.utils.logging import get_logger

logger = get_logger("app.memory.repository")


def _row_to_memory(row: Any) -> MemoryItem:
    """Map SQLite row to MemoryItem."""
    msg_ids = []
    if row["source_message_ids"]:
        try:
            msg_ids = json.loads(row["source_message_ids"])
        except Exception:
            pass

    channels = []
    if row["source_channels"]:
        try:
            channels = json.loads(row["source_channels"])
        except Exception:
            pass

    return MemoryItem(
        id=row["id"],
        user_id=row["user_id"],
        tier=MemoryTier(row["tier"]),
        period=row["period"],
        text=row["text"],
        importance=row["importance"],
        confidence=float(row["confidence"]),
        category=row["category"],
        source=MemorySource(row["source"]),
        source_message_ids=msg_ids,
        source_snippet=row["source_snippet"],
        source_channels=channels,
        pinned=bool(row["pinned"]),
        access_count=row["access_count"],
        last_accessed_at=row["last_accessed_at"],
        superseded_by=row["superseded_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def save_memory(memory: MemoryItem) -> int:
    """Insert or update a memory item. Scoped to memory.user_id."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        if memory.id is None:
            cur = conn.execute(
                """
                INSERT INTO memories (
                    user_id, tier, period, text, importance, confidence,
                    category, source, source_message_ids, source_snippet,
                    source_channels, pinned, access_count, last_accessed_at,
                    superseded_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.user_id,
                    memory.tier.value,
                    memory.period,
                    memory.text,
                    memory.importance,
                    memory.confidence,
                    memory.category,
                    memory.source.value,
                    json.dumps(memory.source_message_ids),
                    memory.source_snippet,
                    json.dumps(memory.source_channels),
                    1 if memory.pinned else 0,
                    memory.access_count,
                    memory.last_accessed_at,
                    memory.superseded_by,
                    memory.created_at or now_utc,
                    now_utc,
                ),
            )
            memory_id = int(cur.lastrowid or 0)
            return memory_id
        else:
            conn.execute(
                """
                UPDATE memories SET
                    tier = ?, period = ?, text = ?, importance = ?,
                    confidence = ?, category = ?, source = ?,
                    source_message_ids = ?, source_snippet = ?,
                    source_channels = ?, pinned = ?, access_count = ?,
                    last_accessed_at = ?, superseded_by = ?, updated_at = ?,
                    deleted_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    memory.tier.value,
                    memory.period,
                    memory.text,
                    memory.importance,
                    memory.confidence,
                    memory.category,
                    memory.source.value,
                    json.dumps(memory.source_message_ids),
                    memory.source_snippet,
                    json.dumps(memory.source_channels),
                    1 if memory.pinned else 0,
                    memory.access_count,
                    memory.last_accessed_at,
                    memory.superseded_by,
                    now_utc,
                    memory.deleted_at,
                    memory.id,
                    memory.user_id,
                ),
            )
            return memory.id


def get_memory(user_id: int, memory_id: int) -> Optional[MemoryItem]:
    """Retrieve an active memory item by user_id and memory_id."""
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT * FROM memories
            WHERE id = ? AND user_id = ? AND deleted_at IS NULL
            """,
            (memory_id, user_id),
        ).fetchone()
        return _row_to_memory(row) if row else None


def list_memories(
    user_id: int,
    tier: Optional[MemoryTier] = None,
    include_deleted: bool = False,
    limit: int = 100,
) -> List[MemoryItem]:
    """List memories for a specific user, optionally filtered by tier."""
    query = "SELECT * FROM memories WHERE user_id = ?"
    params: List[Any] = [user_id]

    if not include_deleted:
        query += " AND deleted_at IS NULL"
    if tier:
        query += " AND tier = ?"
        params.append(tier.value)

    query += " ORDER BY pinned DESC, importance DESC, created_at DESC LIMIT ?"
    params.append(limit)

    with transaction() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_memory(r) for r in rows]


def search_memories_fts(
    user_id: int,
    query_text: str,
    limit: int = 25,
) -> List[MemoryItem]:
    """Search memories via SQLite FTS5 index scoped to user_id."""
    raw_text = getattr(query_text, "normalized", query_text)
    clean_q = "".join(c if c.isalnum() or c.isspace() else " " for c in str(raw_text)).strip()
    if not clean_q:
        return []

    tokens = clean_q.split()
    if not tokens:
        return []
    fts_query = " OR ".join(tokens)

    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT m.*, fts.rank
            FROM memories_fts fts
            JOIN memories m ON m.id = fts.memory_id
            WHERE fts.user_id = ? AND memories_fts MATCH ? AND m.deleted_at IS NULL
            ORDER BY fts.rank ASC, m.importance DESC
            LIMIT ?
            """,
            (user_id, fts_query, limit),
        ).fetchall()
        return [_row_to_memory(r) for r in rows]


def pin_memory(user_id: int, memory_id: int, pinned: bool = True) -> bool:
    """Pin or unpin a memory item."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        cur = conn.execute(
            """
            UPDATE memories SET pinned = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND deleted_at IS NULL
            """,
            (1 if pinned else 0, now_utc, memory_id, user_id),
        )
        return cur.rowcount > 0


def hard_delete_memory(user_id: int, memory_id: int) -> bool:
    """Hard-delete a memory item and clean up FTS."""
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM memories WHERE id = ? AND user_id = ?",
            (memory_id, user_id),
        )
        conn.execute("DELETE FROM memories_fts WHERE memory_id = ?", (memory_id,))
        return cur.rowcount > 0


def hard_delete_all_memories(user_id: int) -> int:
    """Hard-delete all memories, profile fields, and link codes for a user."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        count = cur.rowcount
        conn.execute("DELETE FROM memories_fts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM profile_fields WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM link_codes WHERE user_id = ?", (user_id,))
        return count


def touch_memory_access(memory_ids: List[int]) -> None:
    """Reinforce accessed memories by incrementing access count and updating timestamp."""
    if not memory_ids:
        return
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        for mid in memory_ids:
            conn.execute(
                """
                UPDATE memories
                SET access_count = access_count + 1, last_accessed_at = ?
                WHERE id = ?
                """,
                (now_utc, mid),
            )


# --- Profile Fields -----------------------------------------------------------

def save_profile_field(field_item: ProfileFieldItem) -> int:
    """Upsert a structured profile field for user_id with history preservation."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    val_json = json.dumps(field_item.value) if not isinstance(field_item.value, str) else field_item.value

    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM profile_fields WHERE user_id = ? AND key = ?",
            (field_item.user_id, field_item.key),
        ).fetchone()

        if existing:
            history = []
            if existing["history"]:
                try:
                    history = json.loads(existing["history"])
                except Exception:
                    pass
            history.append({
                "value": existing["value"],
                "superseded_at": now_utc,
                "confidence": existing["confidence"],
            })

            conn.execute(
                """
                UPDATE profile_fields SET
                    value = ?, confidence = ?, confirmed = ?,
                    source_memory_id = ?, updated_at = ?, history = ?
                WHERE user_id = ? AND key = ?
                """,
                (
                    val_json,
                    field_item.confidence,
                    1 if field_item.confirmed else 0,
                    field_item.source_memory_id,
                    now_utc,
                    json.dumps(history),
                    field_item.user_id,
                    field_item.key,
                ),
            )
            return int(existing["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO profile_fields (
                    user_id, key, value, confidence, confirmed,
                    source_memory_id, updated_at, history
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]')
                """,
                (
                    field_item.user_id,
                    field_item.key,
                    val_json,
                    field_item.confidence,
                    1 if field_item.confirmed else 0,
                    field_item.source_memory_id,
                    now_utc,
                ),
            )
            return int(cur.lastrowid or 0)


def get_profile_field(user_id: int, key: str) -> Optional[ProfileFieldItem]:
    """Retrieve a single profile field."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM profile_fields WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
        if not row:
            return None
        hist = []
        if row["history"]:
            try:
                hist = json.loads(row["history"])
            except Exception:
                pass
        return ProfileFieldItem(
            id=row["id"],
            user_id=row["user_id"],
            key=row["key"],
            value=row["value"],
            confidence=float(row["confidence"]),
            confirmed=bool(row["confirmed"]),
            source_memory_id=row["source_memory_id"],
            updated_at=row["updated_at"],
            history=hist,
        )


def list_profile_fields(user_id: int) -> List[ProfileFieldItem]:
    """Retrieve all profile fields for a user."""
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM profile_fields WHERE user_id = ? ORDER BY key ASC",
            (user_id,),
        ).fetchall()
        results: List[ProfileFieldItem] = []
        for r in rows:
            hist = []
            if r["history"]:
                try:
                    hist = json.loads(r["history"])
                except Exception:
                    pass
            results.append(
                ProfileFieldItem(
                    id=r["id"],
                    user_id=r["user_id"],
                    key=r["key"],
                    value=r["value"],
                    confidence=float(r["confidence"]),
                    confirmed=bool(r["confirmed"]),
                    source_memory_id=r["source_memory_id"],
                    updated_at=r["updated_at"],
                    history=hist,
                )
            )
        return results


# --- Audit & Raw Ingestion Accounting -----------------------------------------

def log_memory_job(
    job: str,
    user_id: Optional[int],
    status: str,
    stats: Dict[str, Any],
    started_at: str,
    finished_at: Optional[str] = None,
) -> int:
    """Log execution statistics of a memory background job."""
    fin = finished_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO memory_jobs_log (job, user_id, started_at, finished_at, status, stats)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job, user_id, started_at, fin, status, json.dumps(stats)),
        )
        return int(cur.lastrowid or 0)


def get_unprocessed_user_messages(
    user_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieve raw user messages that have not yet had memories extracted."""
    query = """
        SELECT id, external_message_id, sender_id, text, timestamp, created_at, user_id, channel
        FROM messages
        WHERE direction = 'inbound' AND memory_processed_at IS NULL
    """
    params: List[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    query += " ORDER BY id ASC LIMIT ?"
    params.append(limit)

    with transaction() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def mark_messages_memory_processed(message_ids: List[int]) -> None:
    """Mark messages as processed by the memory subsystem."""
    if not message_ids:
        return
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transaction() as conn:
        for mid in message_ids:
            conn.execute(
                "UPDATE messages SET memory_processed_at = ? WHERE id = ?",
                (now_utc, mid),
            )
