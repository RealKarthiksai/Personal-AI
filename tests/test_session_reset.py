"""Tests for non-destructive session resets via message watermark."""

import pytest

from app.database import database, repository
from app.services.chat_service import ChatService
from app.services.tool_router import RESET_PHRASE_REGEX, ToolRouter


class DummySender:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> str:
        self.sent_messages.append((to, text))
        return f"msg_{len(self.sent_messages)}"


class DummyLLM:
    async def generate(self, messages, system_prompt, max_tokens, temperature):
        return "Simulated reply"


@pytest.fixture(autouse=True)
def init_test_db(tmp_path, monkeypatch) -> None:
    test_db = str(tmp_path / "test_karna_reset.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    monkeypatch.setattr("app.security.authorization.is_sender_authorized", lambda s: True)
    database._init_lock = False
    database.init_db()


def test_reset_phrase_regex() -> None:
    """Verify RESET_PHRASE_REGEX matches only whole-message reset phrases."""
    assert RESET_PHRASE_REGEX.match("nevermind")
    assert RESET_PHRASE_REGEX.match("never mind")
    assert RESET_PHRASE_REGEX.match("nevermind.")
    assert RESET_PHRASE_REGEX.match("nevermind!")
    assert RESET_PHRASE_REGEX.match("start over")
    assert RESET_PHRASE_REGEX.match("forget it")
    assert RESET_PHRASE_REGEX.match("drop it")
    assert RESET_PHRASE_REGEX.match("reset")

    # Partial / contextual mentions must NOT trigger reset
    assert not RESET_PHRASE_REGEX.match("nevermind the error, keep going")
    assert not RESET_PHRASE_REGEX.match("don't forget it please")
    assert not RESET_PHRASE_REGEX.match("how do i reset my password")
    assert not RESET_PHRASE_REGEX.match("drop it like it's hot")


@pytest.mark.asyncio
async def test_session_reset_watermark_flow() -> None:
    """Requirement 10: Send 'nevermind' after a conversation, assert subsequent messages have empty history.

    Assert older rows remain in SQLite (non-destructive).
    """
    sender = DummySender()
    chat_svc = ChatService(llm=DummyLLM(), sender=sender)
    sender_id = "test_chat_reset"

    # Turn 1: Normal conversation
    res1 = await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:101",
        text="hello",
        request_id="req-1",
        sender=sender,
    )
    assert res1["sent"] is True

    # History before reset should contain Turn 1 messages
    hist1 = repository.get_active_session_history(sender_id=sender_id)
    assert len(hist1) >= 1
    assert any("hello" in m["text"] for m in hist1)

    # Turn 2: Natural reset "nevermind"
    res2 = await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:102",
        text="nevermind",
        request_id="req-2",
        sender=sender,
    )
    assert res2["sent"] is True
    assert "Fine, dropping it. What's the new plan?" in res2["llm_response"]

    # Verify watermark is recorded and > 0
    watermark = repository.get_session_reset_watermark(sender_id)
    assert watermark > 0

    # History immediately after reset must be empty (watermark covers both 'nevermind' and the reply)
    hist_after_reset = repository.get_active_session_history(sender_id=sender_id)
    assert hist_after_reset == [], f"Expected empty history after reset, got: {hist_after_reset}"

    # Verify rows still exist in messages table (zero destructive delete)
    with repository.transaction() as conn:
        rows = conn.execute("SELECT id, text FROM messages WHERE sender_id = ?", (sender_id,)).fetchall()
        assert len(rows) >= 3  # hello, bot reply, nevermind, bot direct reply
        assert any(r["text"] == "hello" for r in rows)
        assert any(r["text"] == "nevermind" for r in rows)

    # Turn 3: Subsequent message has empty prior history
    res3 = await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:103",
        text="what's up",
        request_id="req-3",
        sender=sender,
    )
    assert res3["sent"] is True

    # Active session history for Turn 3 only includes Turn 3
    hist3 = repository.get_active_session_history(sender_id=sender_id)
    # Only messages after watermark are included
    for m in hist3:
        assert m["id"] > watermark
        assert "hello" not in m["text"]
        assert "nevermind" not in m["text"]


@pytest.mark.asyncio
async def test_partial_nevermind_does_not_reset() -> None:
    """A sentence like 'nevermind the error, keep going' must not reset history."""
    sender = DummySender()
    chat_svc = ChatService(llm=DummyLLM(), sender=sender)
    sender_id = "test_chat_reset"

    # Pre-seed message
    await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:201",
        text="step 1 instructions",
        sender=sender,
    )
    watermark_before = repository.get_session_reset_watermark(sender_id)

    # Send contextual sentence
    res = await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:202",
        text="nevermind the error, keep going",
        sender=sender,
    )

    watermark_after = repository.get_session_reset_watermark(sender_id)
    assert watermark_after == watermark_before
    assert res["tool_result"]["tool_name"] != "reset"
