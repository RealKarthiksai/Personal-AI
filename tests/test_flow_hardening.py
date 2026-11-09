"""Unit tests for flow hardening, bug fixes, repetition penalties, and fast paths."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_service import ChatService
from app.services.llm_client import LLMClient
from app.services.planner_service import PlannerService
from app.services.telegram_handler import (
    TelegramUpdate,
    handle_command,
    handle_text_message,
    parse_update,
)
from app.telegram_bot import _media_message


class DummySender:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []

    async def send_text(self, to: Optional[str] = None, text: str = "", chat_id: Optional[str] = None) -> str:
        target = to or chat_id or ""
        self.sent_messages.append((target, text))
        return "msg_123"

    async def send_chat_action(self, to: str = "", action: str = "typing", chat_id: str = "") -> bool:
        return True


@pytest.mark.asyncio
async def test_telegram_burst_handling_no_attribute_error(monkeypatch) -> None:
    """Verifies that burst processing does not crash with AttributeError on u.timestamp."""
    monkeypatch.setattr("app.security.authorization.is_sender_authorized", lambda *args, **kwargs: True)

    sender = DummySender()
    mock_service = MagicMock(spec=ChatService)
    mock_service.process_inbound = AsyncMock(return_value={"llm_response": "done", "sent": True})

    import time
    base_id = int(time.time() * 1000) % 100000000

    u1 = TelegramUpdate(
        update_id=base_id + 1,
        chat_id=f"chat_test_burst_{base_id}",
        message_id=base_id + 1,
        user_id=123,
        text="part 1",
        is_command=False,
        command=None,
        timestamp=datetime.now(timezone.utc),
    )
    u2 = TelegramUpdate(
        update_id=base_id + 2,
        chat_id=f"chat_test_burst_{base_id}",
        message_id=base_id + 2,
        user_id=123,
        text="part 2",
        is_command=False,
        command=None,
        # Intentionally None to verify default timestamp & safe getattr
        timestamp=None,
    )

    result = await handle_text_message(
        update=u2,
        service=mock_service,
        sender=sender,
        request_id="req_burst_1",
        burst=[u1, u2],
    )

    assert result["type"] == "text"
    assert result["burst_update_ids"] == [base_id + 1, base_id + 2]
    mock_service.process_inbound.assert_awaited_once()
    assert mock_service.process_inbound.call_args.kwargs["text"] == "part 1\npart 2"


@pytest.mark.asyncio
async def test_telegram_reset_command_no_attribute_error(monkeypatch) -> None:
    """Verifies that /reset does not crash on update.timestamp."""
    monkeypatch.setattr("app.security.authorization.is_sender_authorized", lambda *args, **kwargs: True)

    import time
    dynamic_id = int(time.time() * 1000) % 100000000

    sender = DummySender()
    mock_service = MagicMock(spec=ChatService)

    u = TelegramUpdate(
        update_id=dynamic_id,
        chat_id=f"chat_test_reset_{dynamic_id}",
        message_id=dynamic_id,
        user_id=123,
        text="/reset",
        is_command=True,
        command="/reset",
    )

    result = await handle_command(
        update=u,
        service=mock_service,
        sender=sender,
        request_id="req_reset_1",
    )

    assert result["handled"] is True
    assert "reset" in result["reply"].lower()
    assert len(sender.sent_messages) == 1


@pytest.mark.asyncio
async def test_telegram_media_fallback(monkeypatch) -> None:
    """Verifies that non-text messages get a deadpan response instead of being silently ignored."""
    monkeypatch.setattr("app.security.authorization.is_telegram_user_authorized", lambda *args, **kwargs: True)

    mock_update = MagicMock()
    mock_update.effective_chat.id = 998877
    mock_update.effective_user.id = 12345

    mock_client = DummySender()
    monkeypatch.setattr("app.telegram_bot._build_client", lambda: mock_client)

    await _media_message(mock_update, MagicMock())

    assert len(mock_client.sent_messages) == 1
    chat_id, text = mock_client.sent_messages[0]
    assert chat_id == "998877"
    assert "only read text" in text


@pytest.mark.asyncio
async def test_llm_client_penalties_in_payload() -> None:
    """Verifies that presence_penalty, frequency_penalty, and top_p are sent in payload."""
    client = LLMClient()
    client._model_verified = True
    client.model = "qwen3.5-2b"
    client.base_url = "http://127.0.0.1:8001"

    captured_payload = {}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None, headers=None):
            nonlocal captured_payload
            captured_payload = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "Sample output"}}]
            }
            return resp

    with patch("httpx.AsyncClient", MockAsyncClient):
        reply = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            presence_penalty=0.45,
            frequency_penalty=0.35,
            top_p=0.92,
        )

    assert reply == "Sample output"
    assert captured_payload.get("presence_penalty") == 0.45
    assert captured_payload.get("frequency_penalty") == 0.35
    assert captured_payload.get("top_p") == 0.92


@pytest.mark.asyncio
async def test_planner_fast_path_latency_bypass() -> None:
    """Verifies that follow-up detail requests, banter, and reactions bypass LLM in 0ms."""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock()

    planner = PlannerService(llm_client=mock_llm)

    test_fast_paths = [
        "ohh can you explain it in detail",
        "can you explain it in detail",
        "not in a line in detail",
        "explain in detail",
        "tell me more",
        "why is that",
        "how so",
        "soo lame",
        "is that supposed to be a joke",
        "do you know how random u are",
        "Hello! How are you today?",
    ]

    for q in test_fast_paths:
        plan = await planner.plan_tasks(q)
        assert plan.requires_search is False, f"Query '{q}' should not require search"
        assert len(plan.search_queries) == 0

    # Ensure LLM was NEVER called for any of these
    mock_llm.generate.assert_not_called()
