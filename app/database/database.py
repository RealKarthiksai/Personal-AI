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

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    locale TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(channel, external_user_id)
);
CREATE INDEX IF NOT EXISTS idx_identities_user ON identities(user_id);
CREATE INDEX IF NOT EXISTS idx_identities_channel_ext ON identities(channel, external_user_id);

CREATE TABLE IF NOT EXISTS link_codes (
    code TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_link_codes_user ON link_codes(user_id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier TEXT NOT NULL CHECK (tier IN ('daily','weekly','monthly','yearly','core')),
    period TEXT NOT NULL,
    text TEXT NOT NULL,
    importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
    confidence REAL NOT NULL DEFAULT 1.0,
    category TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('explicit','rule','llm','merged')),
    source_message_ids TEXT NOT NULL DEFAULT '[]',
    source_snippet TEXT,
    source_channels TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    superseded_by INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_user_tier ON memories(user_id, tier);
CREATE INDEX IF NOT EXISTS idx_memories_period ON memories(period);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories(deleted_at);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    user_id UNINDEXED,
    text,
    category,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(memory_id, user_id, text, category)
    VALUES (new.id, new.user_id, new.text, new.category);
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_au AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
    INSERT INTO memories_fts(memory_id, user_id, text, category)
    VALUES (new.id, new.user_id, new.text, new.category);
END;

CREATE TABLE IF NOT EXISTS profile_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    source_memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    history TEXT NOT NULL DEFAULT '[]',
    UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_profile_fields_user ON profile_fields(user_id);

CREATE TABLE IF NOT EXISTS memory_jobs_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL,
    stats TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_jobs_job ON memory_jobs_log(job, started_at DESC);
"""

AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_jobs (
    id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram',
    agent TEXT NOT NULL,
    workspace_alias TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('read_only', 'edit')),
    autonomous INTEGER NOT NULL DEFAULT 0,
    task_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_confirm', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out', 'interrupted', 'rejected')),
    pid INTEGER,
    pgid INTEGER,
    conversation_id TEXT,
    snapshot_ref TEXT,
    branch TEXT,
    exit_code INTEGER,
    output_path TEXT,
    output_summary TEXT,
    diff_stat TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    confirmed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON agent_jobs(status);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_created ON agent_jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS agent_confirmations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
    sender_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    telegram_message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_confirmations_job ON agent_confirmations(job_id);
CREATE INDEX IF NOT EXISTS idx_agent_confirmations_nonce ON agent_confirmations(nonce);

CREATE TABLE IF NOT EXISTS agent_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    sender_id TEXT NOT NULL,
    event TEXT NOT NULL,
    job_id TEXT,
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_ts ON agent_audit(ts DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_job ON agent_audit(job_id);
"""

_init_lock: bool = False
_last_initialized_url: Optional[str] = None


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


def init_db(force: bool = False) -> None:
    """Create tables if they do not exist and apply migrations. Safe to call on every startup."""
    global _init_lock, _last_initialized_url
    if not force and _init_lock and _last_initialized_url == config.database_url:
        return
    with transaction() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(MEMORY_SCHEMA)
        conn.executescript(AGENT_SCHEMA)

        # Migration: Add first_indexed_at & published_at_trusted to external_records if missing
        cols_ext = [r["name"] for r in conn.execute("PRAGMA table_info(external_records)").fetchall()]
        if "first_indexed_at" not in cols_ext:
            conn.execute("ALTER TABLE external_records ADD COLUMN first_indexed_at TEXT")
            conn.execute("ALTER TABLE external_records ADD COLUMN published_at_trusted INTEGER DEFAULT 0")
            conn.execute(
                "UPDATE external_records SET first_indexed_at = COALESCE(fetched_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE first_indexed_at IS NULL"
            )

        # Migration: Add user_id, channel, memory_processed_at to messages if missing
        cols_msg = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "user_id" not in cols_msg:
            conn.execute("ALTER TABLE messages ADD COLUMN user_id INTEGER REFERENCES users(id)")
        if "channel" not in cols_msg:
            conn.execute("ALTER TABLE messages ADD COLUMN channel TEXT")
        if "memory_processed_at" not in cols_msg:
            conn.execute("ALTER TABLE messages ADD COLUMN memory_processed_at TEXT")

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
    _last_initialized_url = config.database_url
    logger.info("Database schema initialized with migrations", extra={"request_id": "system", "message_id": "system"})