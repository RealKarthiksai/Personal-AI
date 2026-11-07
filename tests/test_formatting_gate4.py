"""Gate 4: Formatting Engine & Telegram Renderer Bug Regression Tests.

Verifies:
1. Elimination of double numbering: "1. **1.** Item" -> "<b>1. </b>Item", not "**1. 1**".
2. Elimination of lettered sub-lists: Level 1 sub-items render with bullets ("◦"), not "<b>b.</b>" or "<b>c.</b>".
3. Level 2 sub-items render with square bullets ("▪").
4. Block boundary chunking maintains balanced tags.
"""

from __future__ import annotations

from app.formatting.engine import formatting_engine
from app.formatting.parser import MarkdownParser
from app.formatting.renderers.telegram import TelegramRenderer


def test_no_double_numbering_ordered_list():
    raw_md = (
        "1. **1.** AlphaFold Paper\n"
        "2. **2.** LLaMA Architecture\n"
        "3. 3. PyTorch Update"
    )
    chunks = formatting_engine.format_message(raw_md, channel="telegram")
    rendered = "\n".join(chunks)
    # Verify no double numbers appear
    assert "**1. 1**" not in rendered
    assert "<b>1. </b>**1.**" not in rendered
    assert "<b>1. </b>AlphaFold Paper" in rendered
    assert "<b>2. </b>LLaMA Architecture" in rendered
    assert "<b>3. </b>PyTorch Update" in rendered


def test_no_lettered_prefixes_in_sub_items():
    raw_md = (
        "1. Main Project\n"
        "   - Feature A\n"
        "   - Feature B\n"
        "     - Nested Detail"
    )
    chunks = formatting_engine.format_message(raw_md, channel="telegram")
    rendered = "\n".join(chunks)
    # Verify no <b>b.</b> or <b>c.</b> appears
    assert "<b>b.</b>" not in rendered
    assert "<b>c.</b>" not in rendered
    assert "<b>a.</b>" not in rendered
    # Verify clean bullets
    assert "◦ Feature A" in rendered
    assert "◦ Feature B" in rendered
    assert "▪ Nested Detail" in rendered


def test_block_boundary_chunking_balanced():
    """Ensure multi-chunk messages split at block boundaries with balanced tags."""
    parser = MarkdownParser()
    renderer = TelegramRenderer()

    blocks_md = "\n\n".join([
        f"### Section {i}\nParagraph content for section {i} with <b>bold text</b> and <a href=\"https://example.com/{i}\">link</a>."
        for i in range(1, 30)
    ])
    doc = parser.parse(blocks_md)
    chunks = renderer.render(doc, max_length=1000)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000
        # Check tag balance
        assert chunk.count("<b>") == chunk.count("</b>")
        assert chunk.count("<a ") == chunk.count("</a>")
