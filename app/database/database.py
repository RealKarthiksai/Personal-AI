"""SQLite connection management and schema initialization.

Uses the Python standard library `sqlite3` so no additional dependency is
required. All access goes through a connection context manager that guarantees
rollback on failure and close on exit.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS senders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_message_id TEXT UNIQUE,
    sender_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    text TEXT NOT NULL,
    timestamp TEXT,
    status TEXT NOT NULL DEFAULT 'received',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_sender_direction
    ON messages (sender_id, direction);
CREATE INDEX IF NOT EXISTS idx_messages_external_id
    ON messages (external_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_created
    ON messages (created_at);

CREATE TABLE IF NOT EXISTS search_cache (
    query_hash TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS page_cache (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    markdown_content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    input_data TEXT,
    output_summary TEXT,
    duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extracted_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    structured_data TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_hash TEXT,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_search_cache_created
    ON search_cache (created_at);
CREATE INDEX IF NOT EXISTS idx_page_cache_created
    ON page_cache (created_at);
CREATE INDEX IF NOT EXISTS idx_tool_logs_tool
    ON tool_logs (tool_name, created_at);
CREATE INDEX IF NOT EXISTS idx_entities_type_name
    ON extracted_entities (entity_type, name);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    base_url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS external_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    published_at TEXT,
    updated_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS record_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES external_records(id) ON DELETE CASCADE,
    title TEXT,
    description TEXT,
    metadata TEXT,
    content_hash TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feed_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    category TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitor_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id TEXT UNIQUE,
    url TEXT NOT NULL,
    title TEXT,
    last_checked_at TEXT,
    last_changed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    records_ingested INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'telegram',
    recipient_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_external_records_source_type
    ON external_records (source, record_type);
CREATE INDEX IF NOT EXISTS idx_external_records_published
    ON external_records (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_external_records_fetched
    ON external_records (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_external_records_url
    ON external_records (url);
CREATE INDEX IF NOT EXISTS idx_record_versions_record_id
    ON record_versions (record_id, changed_at DESC);
"""

_init_lock: bool = False


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a SQLite connection with row factory and foreign keys enabled."""
    path = db_path or config.database_url
    # Strip the sqlite:/// prefix if present.
    if path.startswith("sqlite:///"):
        path = path[len("sqlite:///"):]
    elif path.startswith("sqlite://"):
        path = path[len("sqlite://"):]

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Provide a transactional scope around a series of operations."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist and apply migrations. Safe to call on every startup."""
    global _init_lock
    if _init_lock:
        return
    with transaction() as conn:
        conn.executescript(SCHEMA)

        # Migration: Add first_indexed_at & published_at_trusted to external_records if missing
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(external_records)").fetchall()]
        if "first_indexed_at" not in cols:
            conn.execute("ALTER TABLE external_records ADD COLUMN first_indexed_at TEXT")
            conn.execute("ALTER TABLE external_records ADD COLUMN published_at_trusted INTEGER DEFAULT 0")
            conn.execute(
                "UPDATE external_records SET first_indexed_at = COALESCE(fetched_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE first_indexed_at IS NULL"
            )

        # Migration: Create delivered_items table for briefing deduplication
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivered_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                record_id INTEGER NOT NULL REFERENCES external_records(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('briefing', 'query')),
                delivered_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_delivered ON delivered_items(user_id, record_id, delivered_at)")

    _init_lock = True
    logger.info("Database schema initialized with migrations", extra={"request_id": "system", "message_id": "system"})