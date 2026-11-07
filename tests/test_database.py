"""Tests for the SQLite repository layer using a temp database."""

from __future__ import annotations

import os
import tempfile

from app.database import database, repository


def _tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _init_temp_db(path: str) -> None:
    """Initialize the schema against a specific database file."""
    from app.database.database import get_connection

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
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def test_sender_and_message_roundtrip() -> None:
    path = _tmp_db_path()
    try:
        _init_temp_db(path)
        # Point repository at the temp DB by monkeypatching config.database_url.
        import app.config as cfg_module

        orig = cfg_module.config.database_url
        cfg_module.config.database_url = f"sqlite:///{path}"
        try:
            sender_id = repository.get_or_create_sender("+15550001111")
            assert isinstance(sender_id, int) and sender_id > 0
            sender_id_2 = repository.get_or_create_sender("+15550001111")
            assert sender_id_2 == sender_id

            mid = repository.create_message(
                external_message_id="wamid.test1",
                sender_id="+15550001111",
                direction="inbound",
                text="hello",
                timestamp="2024-01-01T00:00:00Z",
            )
            assert isinstance(mid, int)

            assert repository.message_exists("wamid.test1") is True
            assert repository.message_exists("wamid.nope") is False

            history = repository.get_recent_history("+15550001111", 10)
            assert len(history) == 1
            assert history[0]["direction"] == "inbound"
            assert history[0]["text"] == "hello"

            repository.create_message(
                external_message_id=None,
                sender_id="+15550001111",
                direction="outbound",
                text="hi there",
            )
            history = repository.get_recent_history("+15550001111", 10)
            assert len(history) == 2
            assert history[0]["direction"] == "inbound"
            assert history[1]["direction"] == "outbound"
        finally:
            cfg_module.config.database_url = orig
    finally:
        os.unlink(path)


def test_history_limit() -> None:
    path = _tmp_db_path()
    try:
        _init_temp_db(path)
        import app.config as cfg_module

        orig = cfg_module.config.database_url
        cfg_module.config.database_url = f"sqlite:///{path}"
        try:
            for i in range(5):
                repository.create_message(
                    external_message_id=f"wamid.limit.{i}",
                    sender_id="+15550001111",
                    direction="inbound",
                    text=f"msg {i}",
                )
            history = repository.get_recent_history("+15550001111", 3)
            assert len(history) == 3
            assert history[0]["text"] == "msg 2"
            assert history[2]["text"] == "msg 4"
        finally:
            cfg_module.config.database_url = orig
    finally:
        os.unlink(path)