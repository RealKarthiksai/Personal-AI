"""Gate 2: Router Skeleton & DIRECT Ops Handlers Tests.

Verifies:
1. Slash commands (/status, /feeds, /watches) return ResponseMode.DIRECT with 0 LLM calls.
2. Unknown slash commands return deterministic error message with ResponseMode.DIRECT (0 LLM calls).
3. Operational queries ("what feeds are you monitoring", "show active watches") route to DIRECT mode.
4. Research queries ("what are the best RSS feeds for AI") route to search/planner, NOT operational feeds.
5. SSRF checks block private IPs, loopback, and metadata services.
6. Trailing punctuation is cleanly stripped from URLs.
7. Word boundaries prevent false positives ("prevent" != "event", "know" != "now").
8. ChatService.process_inbound executes DIRECT mode with zero LLM generate calls.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.chat_service import ChatService
from app.services.tool_router import (
    ResponseMode,
    ToolRouter,
    get_system_status,
    is_ssrf_safe_url,
    tool_router,
)


# ==============================================================================
# 1. Slash Commands & Operational Queries
# ==============================================================================

@pytest.mark.asyncio
async def test_slash_status_direct():
    result = await tool_router.route_and_execute("/status")
    assert result.mode == ResponseMode.DIRECT
    assert result.tool_name == "status"
    assert "Karna System Status" in result.direct
    assert "Last Known" in result.direct


@pytest.mark.asyncio
async def test_slash_help_and_capabilities_direct():
    res1 = await tool_router.route_and_execute("/help")
    assert res1.mode == ResponseMode.DIRECT
    assert res1.tool_name == "help"
    assert "Karna System Capabilities" in res1.direct
    assert "Cline & Antigravity" in res1.direct

    res2 = await tool_router.route_and_execute("can you tell me all the operations u can perform in my system")
    assert res2.mode == ResponseMode.DIRECT
    assert res2.tool_name == "help"
    assert "Karna System Capabilities" in res2.direct
    assert "Local Agent Delegation" in res2.direct


@pytest.mark.asyncio
async def test_slash_feeds_direct():
    result = await tool_router.route_and_execute("/feeds")
    assert result.mode == ResponseMode.DIRECT
    assert result.tool_name == "feeds"


@pytest.mark.asyncio
async def test_slash_watches_direct():
    result = await tool_router.route_and_execute("/watches")
    assert result.mode == ResponseMode.DIRECT
    assert result.tool_name == "watches"


@pytest.mark.asyncio
async def test_unknown_slash_command_direct():
    result = await tool_router.route_and_execute("/unknown_cmd")
    assert result.mode == ResponseMode.DIRECT
    assert result.tool_name == "unknown_command"
    assert "Unknown command <code>/unknown_cmd</code>" in result.direct
    assert "/status" in result.direct


@pytest.mark.asyncio
async def test_operational_query_vs_research_query():
    """Distinguish 'what feeds are you monitoring' (ops) from 'best RSS feeds for AI' (research)."""
    # Operational intent -> DIRECT
    ops_res = await tool_router.route_and_execute("what feeds are you monitoring?")
    assert ops_res.mode == ResponseMode.DIRECT
    assert ops_res.tool_name == "feeds"

    # Research intent -> search / planner (NOT ops)
    research_res = await tool_router.route_and_execute("what are the best RSS feeds for AI?")
    assert ops_res.tool_name != research_res.tool_name
    assert research_res.mode in (ResponseMode.GROUNDED_TEXT, ResponseMode.PASSTHROUGH)


# ==============================================================================
# 2. SSRF URL Safety & Punctuation Stripping
# ==============================================================================

def test_ssrf_safety_checks():
    assert is_ssrf_safe_url("https://example.com/news") is True
    assert is_ssrf_safe_url("http://127.0.0.1:8000/api") is False
    assert is_ssrf_safe_url("http://localhost:8080") is False
    assert is_ssrf_safe_url("http://169.254.169.254/latest/meta-data") is False
    assert is_ssrf_safe_url("http://10.0.0.1/admin") is False
    assert is_ssrf_safe_url("http://192.168.1.1/router") is False


def test_url_extraction_trailing_punctuation():
    text = "Check out this article: https://example.com/article. It is great!"
    urls = tool_router.extract_urls(text)
    assert len(urls) == 1
    assert urls[0] == "https://example.com/article"


# ==============================================================================
# 3. Substring Bug Regressions (Word Boundaries)
# ==============================================================================

@pytest.mark.asyncio
async def test_substring_word_boundaries_no_false_positive():
    """'prevent' must not trigger event logic, and 'know' must not trigger 'now' expiry."""
    # "how to prevent overfitting in pytorch"
    res = await tool_router.route_and_execute("how to prevent overfitting in pytorch")
    assert res.tool_name != "daily_briefing"
    assert res.tool_name != "feeds"


# ==============================================================================
# 4. End-to-End ChatService DIRECT Mode (0 LLM Calls)
# ==============================================================================

@pytest.mark.asyncio
async def test_chat_service_direct_mode_bypasses_llm():
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock()

    mock_sender = MagicMock()
    mock_sender.send_text = AsyncMock(return_value="msg_123")

    chat_svc = ChatService(llm=mock_llm, sender=mock_sender)

    with patch("app.security.authorization.is_sender_authorized", return_value=True):
        # Process /status
        res = await chat_svc.process_inbound(
            sender_id="user_test",
            external_message_id=f"ext_status_{uuid.uuid4().hex[:8]}",
            text="/status",
        )

    assert res["sent"] is True
    assert "Karna System Status" in res["llm_response"]
    # Verify LLM generate was NEVER called
    mock_llm.generate.assert_not_called()
    # Verify sender was called with pre-rendered status
    mock_sender.send_text.assert_called_once()
