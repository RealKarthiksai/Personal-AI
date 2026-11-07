"""Tests for the Telegram client (monkeypatched transport)."""

from __future__ import annotations

import pytest

from app.services.telegram_client import TelegramClient


def _asyncio_run(coro):  # pragma: no cover - test helper
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text or str(json_data)

    def json(self) -> dict:
        return self._json


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.posted: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url, json=None, headers=None, timeout=None):  # noqa: ANN001
        self.posted.append({"url": url, "json": json})
        if self._responses:
            return self._responses.pop(0)
        return _FakeResponse(200, {"ok": True, "result": {"message_id": 999}})


def test_telegram_send_text_success(monkeypatch) -> None:
    resp = _FakeResponse(200, {"ok": True, "result": {"message_id": 12345}})
    import app.config as cfg_module

    orig_token = cfg_module.config.telegram_bot_token
    cfg_module.config.telegram_bot_token = "123456:ABC-DEF"
    try:
        client = TelegramClient()
        monkeypatch.setattr(
            "httpx.AsyncClient", lambda *args, **kwargs: _FakeClient([resp])
        )

        mid = _asyncio_run(client.send_text(chat_id="123456789", text="hello"))
    finally:
        cfg_module.config.telegram_bot_token = orig_token

    assert mid == "12345"


def test_telegram_markdown_fallback_on_400(monkeypatch) -> None:
    # First response fails with 400 Bad Request (parse entities), second response succeeds without parse_mode
    resp1 = _FakeResponse(
        400,
        {"ok": False, "description": "Bad Request: can't parse entities"},
        text="Bad Request: can't parse entities",
    )
    resp2 = _FakeResponse(200, {"ok": True, "result": {"message_id": 54321}})
    fake_client = _FakeClient([resp1, resp2])

    import app.config as cfg_module

    orig_token = cfg_module.config.telegram_bot_token
    cfg_module.config.telegram_bot_token = "123456:ABC-DEF"
    try:
        client = TelegramClient()
        monkeypatch.setattr(
            "httpx.AsyncClient", lambda *args, **kwargs: fake_client
        )

        mid = _asyncio_run(
            client.send_text(chat_id="123456789", text="some_var_with_underscore")
        )
    finally:
        cfg_module.config.telegram_bot_token = orig_token

    assert mid == "54321"
    assert len(fake_client.posted) == 2
    # Verify the second attempt did NOT have parse_mode
    assert "parse_mode" not in fake_client.posted[1]["json"]
