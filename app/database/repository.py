"""Repository layer for senders and messages.

Provides safe, transactional CRUD used by the chat service. Duplicate inbound
webhook delivery is guarded by a unique constraint on external_message_id.
"""

from __future__ import annotations

from typing import List, Optional

from app.database.database import transaction
from app.database.models import Message, Sender
from app.utils.logging import get_logger

logger = get_logger("app.repository")


def get_or_create_sender(phone_number_id: str) -> int:
    """Return the sender id, creating the sender row if necessary."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM senders WHERE phone_number_id = ?",
            (phone_number_id,),
        ).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO senders (phone_number_id) VALUES (?)",
            (phone_number_id,),
        )
        return int(cur.lastrowid)


def message_exists(external_message_id: str) -> bool:
    """Return True if an inbound message with this external id already exists."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE external_message_id = ? LIMIT 1",
            (external_message_id,),
        ).fetchone()
        return row is not None


def create_message(
    *,
    external_message_id: Optional[str],
    sender_id: str,
    direction: str,
    text: str,
    timestamp: Optional[str] = None,
    status: str = "received",
) -> int:
    """Insert a message row and return its new id."""
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages
                (external_message_id, sender_id, direction, text, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (external_message_id, sender_id, direction, text, timestamp, status),
        )
        return int(cur.lastrowid)


def get_recent_history(sender_id: str, limit: int) -> List[dict]:
    """Return the most recent `limit` messages for a sender, oldest first."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT direction, text, timestamp, created_at
            FROM messages
            WHERE sender_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (sender_id, limit),
        ).fetchall()
    # Reverse so oldest comes first (natural conversation order).
    return [
        {
            "direction": row["direction"],
            "text": row["text"],
            "timestamp": row["timestamp"],
            "created_at": row["created_at"],
        }
        for row in reversed(rows)
    ]


def mark_processing(external_message_id: str, status: str) -> None:
    """Update the status of the most recent inbound message matching the id."""
    with transaction() as conn:
        conn.execute(
            "UPDATE messages SET status = ? WHERE external_message_id = ?",
            (status, external_message_id),
        )


def get_message_count(sender_id: str) -> int:
    with transaction() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE sender_id = ?",
            (sender_id,),
        ).fetchone()
        return int(row["c"])