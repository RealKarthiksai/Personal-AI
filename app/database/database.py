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

CREATE INDEX IF NOT EXISTS idx_search_cache_created
    ON search_cache (created_at);
CREATE INDEX IF NOT EXISTS idx_page_cache_created
    ON page_cache (created_at);
CREATE INDEX IF NOT EXISTS idx_tool_logs_tool
    ON tool_logs (tool_name, created_at);
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

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
    """Create tables if they do not exist. Safe to call on every startup."""
    global _init_lock
    if _init_lock:
        return
    with transaction() as conn:
        conn.executescript(SCHEMA)
    _init_lock = True
    logger.info("Database schema initialized", extra={"request_id": "system", "message_id": "system"})