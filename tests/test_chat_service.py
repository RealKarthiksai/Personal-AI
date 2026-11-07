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