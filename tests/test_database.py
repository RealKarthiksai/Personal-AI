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


def test_parse_db_timestamp() -> None:
    from datetime import datetime, timezone
    from app.database.repository import parse_db_timestamp

    assert parse_db_timestamp(None) is None
    assert parse_db_timestamp("") is None
    assert parse_db_timestamp("invalid-date") is None

    # SQLite standard datetime('now') format
    dt = parse_db_timestamp("2026-11-07 14:00:00")
    assert dt == datetime(2026, 11, 7, 14, 0, 0, tzinfo=timezone.utc)

    # ISO format with Z
    dt_z = parse_db_timestamp("2026-11-07T14:00:00Z")
    assert dt_z == datetime(2026, 11, 7, 14, 0, 0, tzinfo=timezone.utc)

    # ISO format with timezone offset
    dt_tz = parse_db_timestamp("2026-11-07T19:30:00+05:30")
    assert dt_tz.timestamp() == datetime(2026, 11, 7, 14, 0, 0, tzinfo=timezone.utc).timestamp()


def test_active_session_history_timeout_and_gap() -> None:
    path = _tmp_db_path()
    try:
        _init_temp_db(path)
        import app.config as cfg_module
        from datetime import datetime, timezone

        orig = cfg_module.config.database_url
        cfg_module.config.database_url = f"sqlite:///{path}"
        try:
            # 1. Empty history
            ref = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
            h = repository.get_active_session_history("+15550001111", limit=6, timeout_seconds=1800, reference_time=ref)
            assert h == []

            # 2. Insert messages from an old conversation (2 hours prior)
            repository.create_message(
                external_message_id="old_1",
                sender_id="+15550001111",
                direction="inbound",
                text="tell me about Samsung deals",
                created_at="2026-11-07 10:00:00",
            )
            repository.create_message(
                external_message_id="old_2",
                sender_id="+15550001111",
                direction="outbound",
                text="Here are Samsung deals...",
                created_at="2026-11-07 10:00:30",
            )

            # Query at 12:00:00 (elapsed = 1h 59m 30s > 30m timeout) -> session expired!
            h_expired = repository.get_active_session_history(
                "+15550001111",
                limit=6,
                timeout_seconds=1800,
                reference_time=ref,
            )
            assert h_expired == []

            # 3. User sends a message at 12:00:00 (new session starts)
            repository.create_message(
                external_message_id="new_inbound_1",
                sender_id="+15550001111",
                direction="inbound",
                text="hello",
                created_at="2026-11-07 12:00:00",
            )
            repository.create_message(
                external_message_id="new_outbound_1",
                sender_id="+15550001111",
                direction="outbound",
                text="Hey! How's it going?",
                created_at="2026-11-07 12:00:05",
            )

            # User sends follow-up at 12:02:00 (within 30m timeout window)
            ref_active = datetime(2026, 11, 7, 12, 2, 0, tzinfo=timezone.utc)
            repository.create_message(
                external_message_id="new_inbound_2",
                sender_id="+15550001111",
                direction="inbound",
                text="what is the weather today?",
                created_at="2026-11-07 12:02:00",
            )

            h_active = repository.get_active_session_history(
                "+15550001111",
                limit=6,
                timeout_seconds=1800,
                reference_time=ref_active,
                exclude_external_id="new_inbound_2",
            )
            # Old Samsung messages are cut off by the 2-hour idle gap!
            # Only the 2 messages from 12:00:00 are returned
            assert len(h_active) == 2
            assert h_active[0]["text"] == "hello"
            assert h_active[1]["text"] == "Hey! How's it going?"
        finally:
            cfg_module.config.database_url = orig
    finally:
        os.unlink(path)