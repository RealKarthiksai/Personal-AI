"""Tests for the chat service pipeline with monkeypatched dependencies."""

from __future__ import annotations

from typing import Optional
import pytest

from app.services.chat_service import ChatService


def _asyncio_run(coro):  # pragma: no cover - test helper
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeLLM:
    async def generate(self, messages, system_prompt=None, max_tokens=512, temperature=0.7):  # noqa: ANN001
        return f"Reply to: {messages[-1]['content']}"


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> Optional[str]:
        self.sent.append((to, text))
        return "tg.outbound123"


def test_process_inbound_full_pipeline(monkeypatch, tmp_path) -> None:
    # Use a temp DB so tests don't touch the real one.
    db_path = tmp_path / "test.db"
    import app.config as cfg_module
    from app.database import database

    orig_db = cfg_module.config.database_url
    orig_allowed_raw = cfg_module.config.telegram_allowed_user_ids
    orig_allowed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.database_url = f"sqlite:///{db_path}"
    cfg_module.config.telegram_allowed_user_ids = "123456789"
    cfg_module.config.allowed_telegram_user_ids = [123456789]
    try:
        database.init_db()

        service = ChatService(sender=_FakeSender())
        service.llm = _FakeLLM()

        result = _asyncio_run(
            service.process_inbound(
                sender_id="123456789",
                external_message_id="tg:1001",
                text="Hello",
                timestamp="2026-01-01T00:00:00Z",
                request_id="req1",
            )
        )
        assert result["authorized"] is True
        assert result["duplicate"] is False
        assert result["llm_response"] == "Reply to: Hello"
        assert result["sent"] is True
        assert result["message_id"] == "tg.outbound123"
        assert result["error"] is None

        # Duplicate should be skipped.
        result2 = _asyncio_run(
            service.process_inbound(
                sender_id="123456789",
                external_message_id="tg:1001",
                text="Hello again",
                request_id="req2",
            )
        )
        assert result2["duplicate"] is True
        assert result2["llm_response"] is None
    finally:
        cfg_module.config.database_url = orig_db
        cfg_module.config.telegram_allowed_user_ids = orig_allowed_raw
        cfg_module.config.allowed_telegram_user_ids = orig_allowed


def test_unauthorized_sender_rejected(monkeypatch, tmp_path) -> None:
    import app.config as cfg_module
    from app.database import database

    db_path = tmp_path / "test2.db"
    orig_db = cfg_module.config.database_url
    orig_allowed_raw = cfg_module.config.telegram_allowed_user_ids
    orig_allowed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.database_url = f"sqlite:///{db_path}"
    cfg_module.config.telegram_allowed_user_ids = "123456789"
    cfg_module.config.allowed_telegram_user_ids = [123456789]
    try:
        database.init_db()
        service = ChatService()

        result = _asyncio_run(
            service.process_inbound(
                sender_id="999999999",
                external_message_id="tg:9999",
                text="Hi",
                request_id="req3",
            )
        )
        assert result["authorized"] is False
        assert result["error"] == "unauthorized sender"
        assert result["llm_response"] is None
    finally:
        cfg_module.config.database_url = orig_db
        cfg_module.config.telegram_allowed_user_ids = orig_allowed_raw
        cfg_module.config.allowed_telegram_user_ids = orig_allowed


def test_history_compaction_and_token_budget(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "test3.db"
    import app.config as cfg_module
    from app.database import database, repository

    orig_db = cfg_module.config.database_url
    orig_allowed_raw = cfg_module.config.telegram_allowed_user_ids
    orig_allowed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.database_url = f"sqlite:///{db_path}"
    cfg_module.config.telegram_allowed_user_ids = "123456789"
    cfg_module.config.allowed_telegram_user_ids = [123456789]
    try:
        database._init_lock = False
        database.init_db()

        # Insert a massive prior outbound response with a table
        massive_text = "# Prior Table\n\n| Col 1 | Col 2 |\n| --- | --- |\n" + ("| Data 1 | Data 2 |\n" * 50)
        repository.create_message(
            external_message_id="prior_in",
            sender_id="123456789",
            direction="inbound",
            text="Previous question",
        )
        repository.create_message(
            external_message_id=None,
            sender_id="123456789",
            direction="outbound",
            text=massive_text,
        )

        captured_messages = []
        captured_max_tokens = []

        class _RecordingLLM:
            async def generate(self, messages, system_prompt=None, max_tokens=512, temperature=0.7):
                captured_messages.extend(messages)
                captured_max_tokens.append(max_tokens)
                return "Compact reply"

        service = ChatService(sender=_FakeSender())
        service.llm = _RecordingLLM()

        result = _asyncio_run(
            service.process_inbound(
                sender_id="123456789",
                external_message_id="tg:1002",
                text="hello",
                request_id="req4",
            )
        )
        assert result["sent"] is True

        # Verify prior outbound response was compacted
        assistant_msgs = [m for m in captured_messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert len(assistant_msgs[0]["content"]) < len(massive_text)
        assert "[prior response summarized]" in assistant_msgs[0]["content"]

        # Verify max_tokens for casual greeting is 180
        assert captured_max_tokens[0] == 180
    finally:
        cfg_module.config.database_url = orig_db
        cfg_module.config.telegram_allowed_user_ids = orig_allowed_raw
        cfg_module.config.allowed_telegram_user_ids = orig_allowed