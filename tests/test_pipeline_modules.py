"""Unit tests for the Multi-Stage Pipeline modules."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.services.pipeline.telegram_fmt import format_reply, chunks
from app.services.pipeline.planner import plan, SCHEMA as PLAN_SCHEMA
from app.services.pipeline.synth import synthesize
from app.services.pipeline.persona import rewrite, reply_direct
from app.services.pipeline.fetcher import is_safe_url, gather


def test_telegram_fmt_scrubs_ai_tells_and_formats_html() -> None:
    raw = "Certainly! As an AI, I am happy to help. **Paris** is the capital. [1]"
    pages = [{"url": "https://example.com/paris", "text": "Paris is the capital."}]
    res = format_reply(raw, pages)

    assert "Certainly" not in res
    assert "As an AI" not in res
    assert "<b>Paris</b>" in res
    assert '<a href="https://example.com/paris">1</a>' in res
    assert "<i>Sources:</i>" in res


def test_telegram_fmt_chunking() -> None:
    p1 = "Paragraph 1 is short."
    p2 = "Paragraph 2 is also short."
    combined = f"{p1}\n\n{p2}"

    c_full = chunks(combined, limit=100)
    assert len(c_full) == 1
    assert c_full[0] == combined

    c_split = chunks(combined, limit=30)
    assert len(c_split) == 2
    assert c_split[0] == p1
    assert c_split[1] == p2


def test_safe_url_validation() -> None:
    assert is_safe_url("https://en.wikipedia.org/wiki/Python") is True
    assert is_safe_url("http://localhost:8080/secret") is False
    assert is_safe_url("http://127.0.0.1:8000/health") is False
    assert is_safe_url("http://192.168.1.1/admin") is False
    assert is_safe_url("not a url") is False


@pytest.mark.asyncio
async def test_planner_calls_role_with_schema() -> None:
    mock_plan = {
        "needs_search": True,
        "queries": ["latest space launch"],
        "intent": "factual",
        "context": "SpaceX query",
    }
    with patch("app.services.pipeline.planner.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_plan
        res = await plan("When is the next rocket launch?", [("user", "hi")])

    assert res["needs_search"] is True
    assert res["queries"] == ["latest space launch"]
    assert res["intent"] == "factual"
    mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_synth_calls_smart_role() -> None:
    pages = [{"url": "https://example.com", "text": "Rocket launches on Friday [1]."}]
    with patch("app.services.pipeline.synth.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "It launches Friday. [1]"
        summary = await synthesize("When does it launch?", "rocket context", pages)

    assert summary == "It launches Friday. [1]"
    mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_persona_rewrite_keeps_citations() -> None:
    draft = "The rocket launches on Friday. [1]"
    with patch("app.services.pipeline.persona.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "Friday. Try not to miss it. [1]"
        rewritten = await rewrite(draft, "When is the launch?")

    assert "[1]" in rewritten
    assert "Friday" in rewritten
    mock_call.assert_called_once()
