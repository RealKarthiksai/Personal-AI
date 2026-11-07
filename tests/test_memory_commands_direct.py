"""Tests verifying all memory commands execute in ResponseMode.DIRECT with 0 LLM calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.database import database
from app.memory.identity import resolve_user_id
from app.memory.models import MemoryItem, MemoryTier
from app.memory.profile import update_profile_from_fact
from app.memory.repository import save_memory
from app.services.chat_service import ChatService
from app.services.tool_router import ResponseMode, ToolRouter


class _MockSender:
    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    async def send_text(self, to: str, text: str) -> str:
        self.sent_messages.append(text)
        return "msg_123"


@pytest.fixture(autouse=True)
def init_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_karna.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    database._init_lock = False
    database.init_db()
    yield test_db


@pytest.mark.asyncio
async def test_all_memory_commands_zero_llm_calls(monkeypatch):
    mock_llm = AsyncMock()
    # If LLM generate is called, fail the test immediately!
    mock_llm.generate.side_effect = AssertionError("LLMClient.generate must NEVER be called for DIRECT commands!")

    sender = _MockSender()
    monkeypatch.setattr("app.security.authorization.is_sender_authorized", lambda s: True)
    chat_svc = ChatService(llm=mock_llm, sender=sender)
    uid = resolve_user_id("telegram", "direct_cmd_user")

    update_profile_from_fact(user_id=uid, key="name", value="Arthur Dent")
    mem_id = save_memory(
        MemoryItem(
            id=None,
            user_id=uid,
            tier=MemoryTier.DAILY,
            period="2026-11-01",
            text="User never leaves without a towel",
            importance=4,
        )
    )

    commands = [
        "/memory",
        f"/pin {mem_id}",
        f"/unpin {mem_id}",
        "/export",
        "/privacy",
        "/link",
        "/memory_debug towel",
        f"/forget {mem_id}",
        "/forget_all confirm",
    ]

    for idx, cmd in enumerate(commands):
        res = await chat_svc.process_inbound(
            sender_id="direct_cmd_user",
            external_message_id=f"cmd_{idx}",
            text=cmd,
            channel="telegram",
            sender=sender,
        )
        assert res["authorized"] is True
        assert res["sent"] is True
        assert res["tool_result"]["mode"] == ResponseMode.DIRECT.value
        reply = res["llm_response"]
        assert reply is not None
        assert len(reply) > 0
        # Check Telegram single message chunk safety
        assert len(reply) < 10000

    # Ensure mock LLM was NEVER called
    mock_llm.generate.assert_not_called()
