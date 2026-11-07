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


def get_cached_search(query_hash: str, max_age_seconds: int = 3600) -> Optional[str]:
    """Retrieve cached search results JSON if within max_age_seconds."""
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT results_json
            FROM search_cache
            WHERE query_hash = ?
              AND (strftime('%s', 'now') - strftime('%s', created_at)) <= ?
            """,
            (query_hash, max_age_seconds),
        ).fetchone()
        return str(row["results_json"]) if row else None


def set_cached_search(query_hash: str, query: str, results_json: str) -> None:
    """Insert or replace cached search results."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO search_cache (query_hash, query, results_json, created_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(query_hash) DO UPDATE SET
                results_json = excluded.results_json,
                created_at = excluded.created_at
            """,
            (query_hash, query, results_json),
        )


def get_cached_page(url_hash: str, max_age_seconds: int = 86400) -> Optional[dict]:
    """Retrieve cached page markdown and title if within max_age_seconds."""
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT url, title, markdown_content, created_at
            FROM page_cache
            WHERE url_hash = ?
              AND (strftime('%s', 'now') - strftime('%s', created_at)) <= ?
            """,
            (url_hash, max_age_seconds),
        ).fetchone()
        if not row:
            return None
        return {
            "url": row["url"],
            "title": row["title"],
            "markdown_content": row["markdown_content"],
            "created_at": row["created_at"],
        }


def set_cached_page(url_hash: str, url: str, title: str, markdown_content: str) -> None:
    """Insert or replace cached webpage content."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO page_cache (url_hash, url, title, markdown_content, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(url_hash) DO UPDATE SET
                title = excluded.title,
                markdown_content = excluded.markdown_content,
                created_at = excluded.created_at
            """,
            (url_hash, url, title, markdown_content),
        )


def log_tool_execution(
    tool_name: str,
    input_data: str,
    output_summary: str,
    duration_ms: float,
) -> int:
    """Record a tool execution metric row."""
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tool_logs (tool_name, input_data, output_summary, duration_ms)
            VALUES (?, ?, ?, ?)
            """,
            (tool_name, input_data[:1000], output_summary[:1000], duration_ms),
        )
        return int(cursor.lastrowid or 0)


def save_extracted_entity(
    entity_type: str,
    name: str,
    structured_data: str,
    source_url: str,
    content_hash: Optional[str] = None,
) -> int:
    """Insert an extracted entity record (e.g. hackathon, event) into the database."""
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO extracted_entities
                (entity_type, name, structured_data, source_url, content_hash, extracted_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (entity_type, name, structured_data, source_url, content_hash),
        )
        return int(cur.lastrowid or 0)


def get_entities_by_type(entity_type: str, limit: int = 20) -> List[dict]:
    """Retrieve recently extracted entities of a given type."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, entity_type, name, structured_data, source_url, content_hash, extracted_at
            FROM extracted_entities
            WHERE entity_type = ?
            ORDER BY extracted_at DESC, id DESC
            LIMIT ?
            """,
            (entity_type, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "name": row["name"],
                "structured_data": row["structured_data"],
                "source_url": row["source_url"],
                "content_hash": row["content_hash"],
                "extracted_at": row["extracted_at"],
            }
            for row in rows
        ]


def find_entity_by_name(entity_type: str, name: str) -> Optional[dict]:
    """Look up an extracted entity by type and exact or partial name."""
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT id, entity_type, name, structured_data, source_url, content_hash, extracted_at
            FROM extracted_entities
            WHERE entity_type = ? AND name LIKE ?
            ORDER BY extracted_at DESC
            LIMIT 1
            """,
            (entity_type, f"%{name}%"),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "entity_type": row["entity_type"],
            "name": row["name"],
            "structured_data": row["structured_data"],
            "source_url": row["source_url"],
            "content_hash": row["content_hash"],
            "extracted_at": row["extracted_at"],
        }