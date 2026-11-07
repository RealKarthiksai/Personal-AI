"""Tests for the LLM client (uses fake/monkeypatched transport)."""

from __future__ import annotations

import pytest

from app.services.llm_client import LLMClient, LLMResponseError, LLMUnavailableError


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
        self.text = text

    def json(self) -> dict:
        return self._json


class _FakeClient:
    def __init__(self, responses) -> None:
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url, timeout=None):  # noqa: ANN001
        return self._responses[0]

    async def post(self, url, json=None, timeout=None):  # noqa: ANN001
        return self._responses[1]


def test_generate_returns_text(monkeypatch) -> None:
    models_resp = _FakeResponse(200, {"data": [{"id": "llama-3"}]})
    chat_resp = _FakeResponse(
        200,
        {
            "choices": [
                {"message": {"role": "assistant", "content": "Hello there!"}}
            ]
        },
    )

    client = LLMClient()
    client.base_url = "http://127.0.0.1:8001/v1"
    client.model = None
    monkeypatch.setattr(
        "httpx.AsyncClient", lambda *args, **kwargs: _FakeClient([models_resp, chat_resp])
    )

    text = _asyncio_run(client.generate(messages=[{"role": "user", "content": "Hi"}]))
    assert text == "Hello there!"
    assert client.model == "llama-3"


def test_generate_malformed_raises(monkeypatch) -> None:
    models_resp = _FakeResponse(200, {"data": [{"id": "llama-3"}]})
    chat_resp = _FakeResponse(200, {"choices": []})

    client = LLMClient()
    client.base_url = "http://127.0.0.1:8001/v1"
    client.model = "llama-3"
    monkeypatch.setattr(
        "httpx.AsyncClient", lambda *args, **kwargs: _FakeClient([models_resp, chat_resp])
    )

    with pytest.raises(LLMResponseError):
        _asyncio_run(
            client.generate(messages=[{"role": "user", "content": "Hi"}])
        )