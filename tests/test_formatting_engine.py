"""Acceptance test suite for Cross-Platform Message Formatting Engine."""

from __future__ import annotations

import pytest

from app.formatting.engine import MessageFormattingEngine, formatting_engine


@pytest.fixture
def engine() -> MessageFormattingEngine:
    return formatting_engine


# ---------------------------------------------------------------------------
# Test 1: Markdown Headings
# ---------------------------------------------------------------------------
def test_acceptance_1_markdown_headings(engine: MessageFormattingEngine) -> None:
    raw = (
        "# Hackathons in Hyderabad\n\n"
        "Here are the top events.\n\n"
        "## Upcoming in September 2026\n\n"
        "Details about September.\n\n"
        "### Codestorm 2026\n\n"
        "Registration is open."
    )

    # 1. WhatsApp Renderer
    wa_chunks = engine.format_message(raw, channel="whatsapp")
    wa_text = "\n\n".join(wa_chunks)
    # No raw '#' symbols
    assert "#" not in wa_text
    # Uppercase bold with unicode divider for H1 & H2
    assert "*HACKATHONS IN HYDERABAD*" in wa_text
    assert "*UPCOMING IN SEPTEMBER 2026*" in wa_text
    assert "━━━━━━━━━━━━━━━━━━━━━━━━━━" in wa_text
    # Bold capitalization for H3
    assert "*Codestorm 2026*" in wa_text

    # 2. Telegram Renderer
    tg_chunks = engine.format_message(raw, channel="telegram")
    tg_text = "\n\n".join(tg_chunks)
    # No raw '#' symbols
    assert "#" not in tg_text
    # Bold uppercase HTML for H1 & H2
    assert "<b>HACKATHONS IN HYDERABAD</b>" in tg_text
    assert "<b>UPCOMING IN SEPTEMBER 2026</b>" in tg_text
    assert "<code>──────────────────────────</code>" in tg_text
    assert "<b>Codestorm 2026</b>" in tg_text

    # 3. Web Renderer
    web_chunks = engine.format_message(raw, channel="web")
    web_text = "\n\n".join(web_chunks)
    assert "# Hackathons in Hyderabad" in web_text
    assert "## Upcoming in September 2026" in web_text
    assert "### Codestorm 2026" in web_text


# ---------------------------------------------------------------------------
# Test 2: Table with 10 Rows (Zero Information Loss)
# ---------------------------------------------------------------------------
def test_acceptance_2_ten_row_table_zero_loss(engine: MessageFormattingEngine) -> None:
    headers = ["Event Name", "Organizer", "Date", "Location"]
    rows = [
        ["Codestorm", "Narsimha Reddy College", "Sep 15, 2026", "Hyderabad"],
        ["HackOctober", "Tech4Hack", "Oct 04, 2026", "HITEC City"],
        ["Impactech", "CBIT Hyderabad", "Oct 12, 2026", "Gandipet"],
        ["InnoHacks", "JNTU Hyderabad", "Oct 20, 2026", "Kukatpally"],
        ["DevHeat", "VNR VJIET", "Nov 02, 2026", "Bachupally"],
        ["SmartIndia Regional", "AICTE", "Nov 15, 2026", "Gachibowli"],
        ["Web3 Buildathon", "Hyderabad DAO", "Nov 22, 2026", "Madhapur"],
        ["AI Sprint", "T-Hub", "Dec 01, 2026", "Raidurgam"],
        ["BioHackathon", "Genome Valley", "Dec 10, 2026", "Shamirpet"],
        ["CloudCrafters", "AWS User Group", "Dec 20, 2026", "Financial District"],
    ]

    table_md = "| " + " | ".join(headers) + " |\n"
    table_md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for r in rows:
        table_md += "| " + " | ".join(r) + " |\n"

    raw = f"# Major Hackathons\n\n{table_md}\nSummary of all 10 events."

    # 1. WhatsApp Renderer
    wa_chunks = engine.format_message(raw, channel="whatsapp")
    wa_text = "\n\n".join(wa_chunks)
    # No raw ASCII table pipes
    assert "| Event Name |" not in wa_text
    assert "| --- |" not in wa_text
    # Verify ZERO information loss: all 10 entries and their details are present
    for idx, row in enumerate(rows, 1):
        assert f"*{idx}. {row[0]}*" in wa_text
        assert f"• Organizer: {row[1]}" in wa_text
        assert f"• Date: {row[2]}" in wa_text
        assert f"• Location: {row[3]}" in wa_text

    # 2. Telegram Renderer
    tg_chunks = engine.format_message(raw, channel="telegram")
    tg_text = "\n\n".join(tg_chunks)
    # No raw table pipes
    assert "| Event Name |" not in tg_text
    # Verify ZERO information loss on Telegram
    for idx, row in enumerate(rows, 1):
        assert f"<b>{idx}. {row[0]}</b>" in tg_text
        assert f"• <b>Organizer:</b> {row[1]}" in tg_text
        assert f"• <b>Date:</b> {row[2]}" in tg_text
        assert f"• <b>Location:</b> {row[3]}" in tg_text

    # 3. Web Renderer
    web_chunks = engine.format_message(raw, channel="web")
    web_text = "\n\n".join(web_chunks)
    # Verify Markdown table intact
    assert "| Event Name | Organizer | Date | Location |" in web_text
    for row in rows:
        assert f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |" in web_text


# ---------------------------------------------------------------------------
# Test 3: Nested Bullet Points
# ---------------------------------------------------------------------------
def test_acceptance_3_nested_bullet_points(engine: MessageFormattingEngine) -> None:
    raw = (
        "* Level 0 Item 1\n"
        "  * Level 1 Item 1a\n"
        "    * Level 2 Item 1ai\n"
        "* Level 0 Item 2\n"
        "  * Level 1 Item 2a"
    )

    # 1. WhatsApp
    wa_chunks = engine.format_message(raw, channel="whatsapp")
    wa_text = "\n\n".join(wa_chunks)
    assert "• Level 0 Item 1" in wa_text
    assert "  ◦ Level 1 Item 1a" in wa_text
    assert "    ▪ Level 2 Item 1ai" in wa_text
    assert "• Level 0 Item 2" in wa_text
    assert "  ◦ Level 1 Item 2a" in wa_text

    # 2. Telegram
    tg_chunks = engine.format_message(raw, channel="telegram")
    tg_text = "\n\n".join(tg_chunks)
    assert "• Level 0 Item 1" in tg_text
    assert "  ◦ Level 1 Item 1a" in tg_text
    assert "    ▪ Level 2 Item 1ai" in tg_text

    # 3. Web
    web_chunks = engine.format_message(raw, channel="web")
    web_text = "\n\n".join(web_chunks)
    assert "Level 0 Item 1" in web_text
    assert "Level 1 Item 1a" in web_text


# ---------------------------------------------------------------------------
# Test 4: Code Blocks and URLs
# ---------------------------------------------------------------------------
def test_acceptance_4_code_blocks_and_urls(engine: MessageFormattingEngine) -> None:
    raw = (
        "Check documentation at [FastAPI Guide](https://fastapi.tiangolo.com) for details.\n\n"
        "Run `pytest -v` to run the test suite.\n\n"
        "```python\n"
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}!'\n"
        "```"
    )

    # 1. WhatsApp: links adapted as Label (URL), backticks preserved
    wa_chunks = engine.format_message(raw, channel="whatsapp")
    wa_text = "\n\n".join(wa_chunks)
    assert "FastAPI Guide (https://fastapi.tiangolo.com)" in wa_text
    assert "[FastAPI Guide](" not in wa_text
    assert "`pytest -v`" in wa_text
    assert "```[python]" in wa_text
    assert "def greet(name: str) -> str:" in wa_text

    # 2. Telegram: HTML <a href="...">, <code>, <pre>
    tg_chunks = engine.format_message(raw, channel="telegram")
    tg_text = "\n\n".join(tg_chunks)
    assert '<a href="https://fastapi.tiangolo.com">FastAPI Guide</a>' in tg_text
    assert "<code>pytest -v</code>" in tg_text
    assert '<pre><code class="language-python">def greet(name: str) -&gt; str:\n    return f\'Hello, {name}!\'</code></pre>' in tg_text

    # 3. Web: GFM intact
    web_chunks = engine.format_message(raw, channel="web")
    web_text = "\n\n".join(web_chunks)
    assert "[FastAPI Guide](https://fastapi.tiangolo.com)" in web_text
    assert "`pytest -v`" in web_text
    assert "```python" in web_text


# ---------------------------------------------------------------------------
# Test 5: Long Response Splitting (> 4000 chars)
# ---------------------------------------------------------------------------
def test_acceptance_5_long_response_splitting(engine: MessageFormattingEngine) -> None:
    sections = []
    for i in range(1, 11):
        sections.append(f"## Section {i}: Research Topic {i}\n\n" + ("Detailed analysis paragraph with facts and data. " * 20))
    long_doc = "\n\n".join(sections)
    assert len(long_doc) > 7000

    # 1. WhatsApp: split into chunks <= 4000
    wa_chunks = engine.format_message(long_doc, channel="whatsapp", max_length=4000)
    assert len(wa_chunks) >= 2
    for chunk in wa_chunks:
        assert len(chunk) <= 4000
        # Verify split is at section or paragraph boundaries
        assert not chunk.startswith("\n")
        assert not chunk.endswith("\n")

    # 2. Telegram: split into chunks <= 4000, safe tags
    tg_chunks = engine.format_message(long_doc, channel="telegram", max_length=4000)
    assert len(tg_chunks) >= 2
    for chunk in tg_chunks:
        assert len(chunk) <= 4000
        # Verify no open tag corruption like dangling <b without </b>
        b_opens = chunk.count("<b>")
        b_closes = chunk.count("</b>")
        assert b_opens == b_closes

    # 3. Web: single chunk or full document without small splits
    web_chunks = engine.format_message(long_doc, channel="web", max_length=32000)
    assert len(web_chunks) == 1
    assert len(web_chunks[0]) > 7000


# ---------------------------------------------------------------------------
# Test 6: Emojis and Special Characters
# ---------------------------------------------------------------------------
def test_acceptance_6_emojis_and_special_characters(engine: MessageFormattingEngine) -> None:
    raw = (
        "🚀 Launch status: 100% SUCCESS! 💡 Quick tip: Always test your code.\n\n"
        "Special chars & logic: 10 > 5 and 3 < 8. Compare 'single' and \"double\" quotes.\n\n"
        "XML/HTML test: <custom-tag>value</custom-tag> &amp; entities."
    )

    # 1. WhatsApp
    wa_chunks = engine.format_message(raw, channel="whatsapp")
    wa_text = "\n\n".join(wa_chunks)
    assert "🚀 Launch status: 100% SUCCESS!" in wa_text
    assert "💡 Quick tip:" in wa_text
    assert "10 > 5 and 3 < 8" in wa_text

    # 2. Telegram: strictly escapes &, <, >
    tg_chunks = engine.format_message(raw, channel="telegram")
    tg_text = "\n\n".join(tg_chunks)
    assert "🚀 Launch status: 100% SUCCESS!" in tg_text
    assert "💡 Quick tip:" in tg_text
    assert "10 &gt; 5 and 3 &lt; 8" in tg_text
    assert "&lt;custom-tag&gt;value&lt;/custom-tag&gt;" in tg_text
    assert "&amp;amp;" in tg_text or "&amp;" in tg_text

    # 3. Web
    web_chunks = engine.format_message(raw, channel="web")
    web_text = "\n\n".join(web_chunks)
    assert "🚀 Launch status: 100% SUCCESS!" in web_text


# ---------------------------------------------------------------------------
# Test 7: Malformed or Incomplete Structured Response
# ---------------------------------------------------------------------------
def test_acceptance_7_malformed_incomplete_input(engine: MessageFormattingEngine) -> None:
    raw_malformed = (
        "### Partially Cut Off Header\n\n"
        "```python\n"
        "def unclosed_code():\n"
        "    x = 10\n"
        "    # Missing closing fence\n\n"
        "| Cut-off Table Header | Col 2\n"
        "| --- | ---\n"
        "| Row 1 missing end\n\n"
        "[Unclosed link(https://example.com"
    )

    # Should not raise exception on any channel
    wa_chunks = engine.format_message(raw_malformed, channel="whatsapp")
    assert len(wa_chunks) > 0
    wa_text = "\n\n".join(wa_chunks)
    assert "unclosed_code" in wa_text
    assert "Row 1 missing end" in wa_text

    tg_chunks = engine.format_message(raw_malformed, channel="telegram")
    assert len(tg_chunks) > 0
    tg_text = "\n\n".join(tg_chunks)
    assert "unclosed_code" in tg_text

    web_chunks = engine.format_message(raw_malformed, channel="web")
    assert len(web_chunks) > 0


# ---------------------------------------------------------------------------
# Edge Cases & Channels
# ---------------------------------------------------------------------------
def test_unknown_channel_defaults_to_web(engine: MessageFormattingEngine) -> None:
    raw = "# Header\n\nSome text."
    chunks = engine.format_message(raw, channel="discord_or_slack")
    assert len(chunks) == 1
    assert "# Header" in chunks[0]


def test_empty_or_whitespace_message(engine: MessageFormattingEngine) -> None:
    assert engine.format_message("", channel="whatsapp") == []
    assert engine.format_message("   \n\n  ", channel="telegram") == []


def test_parser_exception_resilient_fallback(monkeypatch, engine: MessageFormattingEngine) -> None:
    # Force parser to raise an unexpected error
    def _exploding_parse(text):
        raise RuntimeError("Simulated crash in parser")

    monkeypatch.setattr(engine.parser, "parse", _exploding_parse)
    raw = "# Test Title\n\n| Col1 | Col2 |\n| --- | --- |\n| A | B |\n\n[Visit](https://example.com)"
    chunks = engine.format_message(raw, channel="whatsapp")
    assert len(chunks) > 0
    text = "\n\n".join(chunks)
    # Fallback should strip broken markdown headers and link syntax
    assert "# Test Title" not in text
    assert "[Visit](" not in text


@pytest.mark.asyncio
async def test_telegram_client_multi_chunk_delivery(monkeypatch) -> None:
    from app.services.telegram_client import TelegramClient
    import app.config as cfg_module

    posted_payloads = []

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None, timeout=None):
            posted_payloads.append(json)
            mid = 1000 + len(posted_payloads)
            return type("_FakeResp", (), {
                "status_code": 200,
                "text": '{"ok": true}',
                "json": lambda self: {"ok": True, "result": {"message_id": mid}},
            })()

    orig_token = cfg_module.config.telegram_bot_token
    cfg_module.config.telegram_bot_token = "123456:FAKE_TOKEN"
    try:
        monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _MockClient())
        client = TelegramClient()

        # Send a long message that splits into 2+ chunks
        sections = [f"## Topic {i}\n\n" + ("Details and data. " * 300) for i in range(1, 5)]
        long_text = "\n\n".join(sections)
        mid = await client.send_text(chat_id="123456", text=long_text)

        assert mid is not None
        assert len(posted_payloads) >= 2
        for p in posted_payloads:
            assert p["chat_id"] == "123456"
            assert p["parse_mode"] == "HTML"
            assert len(p["text"]) <= 4000
    finally:
        cfg_module.config.telegram_bot_token = orig_token

