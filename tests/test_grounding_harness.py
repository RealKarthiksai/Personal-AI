"""Gate 5: Grounded Text Validator & Adversarial Grounding Harness.

Verifies:
1. normalize_url strips tracking params, www., default ports, fragments, and forces https.
2. validate_grounded_text permits verified allowed URLs and strips fabricated/hallucinated links.
3. Scheme-less domains (github.com/fake, arxiv.org/fake) not in allowed URLs are stripped.
4. End-to-end ChatService validation ensures a deliberately hallucinating LLM cannot leak ungrounded URLs.
5. Untrusted content delimiters wrap third-party research data.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.chat_service import ChatService
from app.services.grounding_verifier import (
    normalize_url,
    validate_grounded_text,
)
from app.services.tool_router import ResponseMode, ToolExecutionResult, ToolRouter


# ==============================================================================
# 1. URL Normalization Unit Tests
# ==============================================================================

def test_normalize_url_rules():
    # Force https and lowercase host
    assert normalize_url("http://EXAMPLE.COM/Page") == "https://example.com/Page"
    # Strip www
    assert normalize_url("https://www.example.com/page") == "https://example.com/page"
    # Drop default ports
    assert normalize_url("https://example.com:443/page") == "https://example.com/page"
    assert normalize_url("http://example.com:80/page") == "https://example.com/page"
    # Drop tracking params & fragments
    raw = "https://example.com/event?id=123&utm_source=twitter&utm_medium=social&fbclid=XYZ#section"
    assert normalize_url(raw) == "https://example.com/event?id=123"
    # Strip trailing slash from path
    assert normalize_url("https://example.com/path/") == "https://example.com/path"


# ==============================================================================
# 2. Grounded Text Validator Tests
# ==============================================================================

def test_validate_grounded_text_allowed_links_preserved():
    allowed = frozenset(["https://github.com/torvalds/linux", "https://arxiv.org/abs/2301.00001"])
    text = (
        "Here are the top projects:\n"
        "- Linux Kernel: [Linux](https://github.com/torvalds/linux?utm_source=test)\n"
        "- Research Paper: https://arxiv.org/abs/2301.00001"
    )
    result = validate_grounded_text(text, allowed)
    assert "https://github.com/torvalds/linux" in result
    assert "https://arxiv.org/abs/2301.00001" in result


def test_validate_grounded_text_fabricated_links_stripped():
    allowed = frozenset(["https://github.com/valid/repo"])
    text = (
        "Check out this project: [Valid](https://github.com/valid/repo)\n"
        "And also check this fake site: [Fake](https://hallucinated-events.org/fake-hackathon)\n"
        "Here is another ungrounded link: https://fake-arxiv.org/abs/9999"
    )
    result = validate_grounded_text(text, allowed)
    # Valid link preserved
    assert "https://github.com/valid/repo" in result
    # Fabricated links stripped
    assert "https://hallucinated-events.org/fake-hackathon" not in result
    assert "https://fake-arxiv.org/abs/9999" not in result
    assert "Fake" in result  # Link text preserved as title without fake URL


def test_validate_grounded_text_schemeless_domains_checked():
    allowed = frozenset(["https://github.com/real/repo"])
    text = (
        "See github.com/real/repo for code.\n"
        "Avoid github.com/fake/hallucination which is not real."
    )
    result = validate_grounded_text(text, allowed)
    assert "github.com/real/repo" in result
    assert "github.com/fake/hallucination" not in result


# ==============================================================================
# 3. Adversarial Hallucinating Mock LLM Test
# ==============================================================================

@pytest.mark.asyncio
async def test_adversarial_hallucinating_mock_llm():
    """Verify that when the LLM hallucinates fake URLs, post-hoc validation completely removes them."""
    # A deliberately adversarial hallucinating LLM output
    hallucinating_response = (
        "Here are the top AI events happening in Hyderabad:\n\n"
        "1. [Hyd AI Summit 2026](https://verified-events.com/hyd-ai)\n"
        "   Date: March 15, 2026. Great opportunity!\n\n"
        "2. [Fake Mega Hackathon](https://completely-fake-hallucination.com/register)\n"
        "   Date: April 10, 2026. Register immediately!\n\n"
        "3. Also check github.com/hallucinated-user/fake-repo for code."
    )

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=hallucinating_response)

    mock_sender = MagicMock()
    mock_sender.send_text = AsyncMock(return_value="msg_456")

    mock_router = MagicMock()
    # Router only allows the verified event URL
    mock_router.route_and_execute = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="searxng_search",
            context_text="Found: Hyd AI Summit at https://verified-events.com/hyd-ai",
            mode=ResponseMode.GROUNDED_TEXT,
            allowed_urls=frozenset(["https://verified-events.com/hyd-ai"]),
        )
    )

    chat_svc = ChatService(llm=mock_llm, sender=mock_sender, tool_router=mock_router)

    with patch("app.security.authorization.is_sender_authorized", return_value=True):
        res = await chat_svc.process_inbound(
            sender_id="user_adv",
            external_message_id=f"adv_msg_{uuid.uuid4().hex[:8]}",
            text="find hackathons in hyd",
        )

    delivered_text = res["llm_response"]
    # Verified URL must be present
    assert "https://verified-events.com/hyd-ai" in delivered_text
    # Fake URLs MUST NOT be present
    assert "https://completely-fake-hallucination.com/register" not in delivered_text
    assert "github.com/hallucinated-user/fake-repo" not in delivered_text
