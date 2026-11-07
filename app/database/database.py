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