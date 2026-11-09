"""Tests for strict conversational memory gating, stopword stripping, and FTS5 AND multi-term matching."""

import pytest

from app.database import database
from app.memory.identity import resolve_user_id
from app.memory.models import MemoryItem, MemorySource, MemoryTier
from app.memory.repository import save_memory, search_memories_fts
from app.memory.retrieval import build_memory_context, extract_content_terms


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch) -> None:
    test_db = str(tmp_path / "test_karna_gate.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    database._init_lock = False
    database.init_db()


def test_extract_content_terms_strips_conversational_noise() -> None:
    """Conversational filler words ('know', 'random', 'lame', 'joke', 'mean', 'supposed', etc.) must be stripped."""
    assert extract_content_terms("do you know how random u are") == []
    assert extract_content_terms("soo lame") == []
    assert extract_content_terms("is that supposed to be a joke") == []
    assert extract_content_terms("omg tf u mean") == []
    assert extract_content_terms("what did i note about hackathons") == ["hackathons"]
    assert extract_content_terms("AI summit registration") == ["ai", "summit", "registration"]


def test_memory_context_not_injected_on_banter_despite_seeded_hackathons() -> None:
    """Requirement 9: Seed DB with hackathon daily memories, send 'do you know how random u are',

    assert the memory is NOT injected into the prompt (build_memory_context returns '').
    """
    user_id = resolve_user_id("telegram", "test_user_banter")
    # Seed daily hackathon memories into DB
    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="Telangana AI Summit hackathon happening on Nov 28",
            importance=4,
            confidence=0.9,
            source=MemorySource.RULE,
        )
    )
    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="Devfolio Web3 Hackathon happening on Nov 21",
            importance=4,
            confidence=0.9,
            source=MemorySource.RULE,
        )
    )

    # 1. Banter query "do you know how random u are"
    ctx1 = build_memory_context(user_id=user_id, query="do you know how random u are")
    assert ctx1 == "", f"Expected empty memory context for banter, got: {ctx1}"
    assert "Nov 28" not in ctx1
    assert "<user_memory_data>" not in ctx1

    # 2. Banter query "soo lame"
    ctx2 = build_memory_context(user_id=user_id, query="soo lame")
    assert ctx2 == ""

    # 3. Banter query "is that supposed to be a joke"
    ctx3 = build_memory_context(user_id=user_id, query="is that supposed to be a joke")
    assert ctx3 == ""

    # 4. Explicit recall for hackathons MUST find the memory
    ctx_explicit = build_memory_context(user_id=user_id, query="what did i note about hackathons")
    assert "Nov 28" in ctx_explicit
    assert "<user_memory_data>" in ctx_explicit


def test_fts5_multiterm_and_matching() -> None:
    """Requirement 6: Multi-term queries join terms with AND, not OR."""
    user_id = resolve_user_id("telegram", "test_user_fts")
    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="He told a funny joke at lunch",
            importance=3,
            confidence=0.8,
            source=MemorySource.RULE,
        )
    )
    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="Selected random seed for algorithm",
            importance=3,
            confidence=0.8,
            source=MemorySource.RULE,
        )
    )
    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="A truly random joke generator written in Python",
            importance=5,
            confidence=0.9,
            source=MemorySource.RULE,
        )
    )

    # Query with both terms: should ONLY match the item that has BOTH
    results = search_memories_fts(user_id=user_id, query_text="random joke")
    assert len(results) == 1
    assert "random joke generator" in results[0].text


@pytest.mark.asyncio
async def test_regression_e2e_random_u_are_does_not_leak_hackathon_memories(monkeypatch) -> None:
    """End-to-end regression test: Seed daily hackathons, call ChatService with 'do you know how random u are'.

    Verify that:
    1. Memory context is empty and no hackathon dates are passed to the model.
    2. LLM response does not mention hackathons or Nov dates.
    """
    import re
    from app.services.chat_service import ChatService

    captured_prompt = []

    class CapturingLLM:
        async def generate(self, messages, system_prompt, max_tokens, temperature):
            for m in messages:
                captured_prompt.append(m["content"])
            return "I'm an assistant, not a random number generator."

    class DummySender:
        async def send_text(self, to, text):
            return "msg-1"

    monkeypatch.setattr("app.security.authorization.is_sender_authorized", lambda s: True)
    sender_id = "test_user_regression"
    user_id = resolve_user_id("telegram", sender_id)

    save_memory(
        MemoryItem(
            user_id=user_id,
            tier=MemoryTier.DAILY,
            period="2026-11-10",
            text="Telangana AI Summit hackathon happening on Nov 28",
            importance=5,
            confidence=0.9,
            source=MemorySource.RULE,
        )
    )

    chat_svc = ChatService(llm=CapturingLLM(), sender=DummySender())
    res = await chat_svc.process_inbound(
        sender_id=sender_id,
        external_message_id="tg:99909",
        text="do you know how random u are",
        sender=DummySender(),
    )

    full_prompt_text = " ".join(captured_prompt)
    assert "Nov 28" not in full_prompt_text
    assert "<user_memory_data>" not in full_prompt_text
    assert "hackathon" not in full_prompt_text.lower()
    assert not re.search(r"\bNov\s+\d+\b", res["llm_response"] or "")
