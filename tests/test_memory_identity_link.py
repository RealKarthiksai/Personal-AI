"""Tests for cross-channel identity resolution, account linking, and user data isolation."""

from __future__ import annotations

import pytest

from app.database import database
from app.memory.identity import (
    generate_link_code,
    get_user_identities,
    redeem_link_code,
    resolve_user_id,
)
from app.memory.models import MemoryItem, MemoryTier
from app.memory.repository import (
    hard_delete_memory,
    list_memories,
    save_memory,
    search_memories_fts,
)


@pytest.fixture(autouse=True)
def init_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_karna.db")
    monkeypatch.setattr("app.config.config.database_url", test_db)
    database._init_lock = False
    database.init_db()
    yield test_db


def test_resolve_user_id_creates_and_retrieves():
    uid1 = resolve_user_id("telegram", "tg_user_101")
    assert uid1 > 0

    # Same identity returns same canonical user_id
    uid2 = resolve_user_id("telegram", "tg_user_101")
    assert uid1 == uid2

    # Different identity gets distinct user_id
    uid3 = resolve_user_id("telegram", "tg_user_202")
    assert uid3 != uid1


def test_generate_and_redeem_link_code():
    uid_telegram = resolve_user_id("telegram", "alice_tg")
    uid_whatsapp = resolve_user_id("whatsapp", "alice_wa")
    assert uid_telegram != uid_whatsapp

    # Generate 6-digit link code for Telegram user
    code = generate_link_code(uid_telegram)
    assert len(code) == 6
    assert code.isdigit()

    # WhatsApp user enters the code to link identities
    success, msg, _ = redeem_link_code(
        channel="whatsapp",
        external_user_id="alice_wa",
        code=code,
    )
    assert success is True
    assert "successfully linked" in msg.lower()

    # Now resolving whatsapp returns alice's canonical user_id!
    resolved_wa_uid = resolve_user_id("whatsapp", "alice_wa")
    assert resolved_wa_uid == uid_telegram

    # Verify both channels are visible in user identities
    identities = get_user_identities(uid_telegram)
    chans = {i["channel"] for i in identities}
    assert "telegram" in chans
    assert "whatsapp" in chans


def test_redeem_invalid_or_expired_code():
    uid = resolve_user_id("telegram", "bob_tg")
    code = generate_link_code(uid)

    # 1. Invalid code
    ok, err, _ = redeem_link_code(code="999999", channel="whatsapp", external_user_id="bob_wa")
    assert ok is False
    assert "invalid" in err.lower()

    # 2. Re-using same code
    ok2, _, _ = redeem_link_code(code=code, channel="whatsapp", external_user_id="bob_wa")
    assert ok2 is True

    # Redeeming again fails (already used)
    ok3, err3, _ = redeem_link_code(code=code, channel="web", external_user_id="bob_web")
    assert ok3 is False


def test_cross_user_memory_isolation():
    uid_alice = resolve_user_id("telegram", "alice_user")
    uid_bob = resolve_user_id("telegram", "bob_user")

    # Save memory for Alice
    save_memory(
        MemoryItem(
            id=None,
            user_id=uid_alice,
            tier=MemoryTier.CORE,
            period="2026-11-01",
            text="Alice's confidential project code name is Project Chimera",
            importance=5,
        )
    )

    # Save memory for Bob
    save_memory(
        MemoryItem(
            id=None,
            user_id=uid_bob,
            tier=MemoryTier.CORE,
            period="2026-11-01",
            text="Bob's public project is Website Redesign",
            importance=4,
        )
    )

    # Alice's memories should not include Bob's
    alice_memories = list_memories(user_id=uid_alice)
    assert len(alice_memories) == 1
    assert "Chimera" in alice_memories[0].text

    # Bob's memories should not include Alice's
    bob_memories = list_memories(user_id=uid_bob)
    assert len(bob_memories) == 1
    assert "Website Redesign" in bob_memories[0].text

    # FTS5 search by Bob cannot find Alice's confidential Chimera
    bob_search = search_memories_fts(user_id=uid_bob, query_text="Chimera")
    assert len(bob_search) == 0

    # Bob cannot delete Alice's memory
    alice_mem_id = alice_memories[0].id
    deleted = hard_delete_memory(user_id=uid_bob, memory_id=alice_mem_id)  # type: ignore
    assert deleted is False

    # Alice still has her memory
    assert len(list_memories(user_id=uid_alice)) == 1
