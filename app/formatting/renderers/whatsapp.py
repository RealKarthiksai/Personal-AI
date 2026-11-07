"""WhatsApp message renderer.

Transforms structured document blocks into clean, universally readable text
optimized for WhatsApp without raw Markdown headings (#) or raw tables (|).
"""

from __future__ import annotations

import re
from typing import List

from app.formatting.models import (
    Block,
    CodeBlock,
    DividerBlock,
    Document,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)
from app.formatting.renderers.base import split_into_chunks

UNICODE_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━"


def clean_whatsapp_inline(text: str) -> str:
    """Transform markdown inline elements to WhatsApp-supported formatting."""
    if not text:
        return ""

    s = text

    # Convert Markdown links [text](url) -> text (url)
    def _link_sub(m: re.Match) -> str:
        label = m.group(1).strip()
        url = m.group(2).strip()
        if label.lower() in ("link", "url", "here", "click here"):
            return url
        if label == url:
            return url
        return f"{label} ({url})"

    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", _link_sub, s)

    # Convert GFM bold **text** or __text__ -> *text*
    s = re.sub(r"(?:\*\*|__)(.*?)(?:\*\*|__)", r"*\1*", s)

    # Convert strike-through ~~text~~ -> ~text~
    s = re.sub(r"~~(.*?)~~", r"~\1~", s)

    # Clean up double asterisks leftovers
    s = s.replace("**", "*")

    return s.strip()


class WhatsAppRenderer:
    """Renders Document IR into beautiful, native WhatsApp text."""

    def render(self, doc: Document, max_length: int = 4000) -> List[str]:
        """Convert a Document into one or more WhatsApp-ready text chunks."""
        sections: List[str] = []

        for block in doc.blocks:
            rendered = self._render_block(block)
            if rendered:
                sections.append(rendered)

        full_text = "\n\n".join(sections).strip()
        return split_into_chunks(full_text, max_length=max_length)

    def _render_block(self, block: Block) -> str:
        if isinstance(block, HeadingBlock):
            return self._render_heading(block)
        elif isinstance(block, TableBlock):
            return self._render_table(block)
        elif isinstance(block, ListBlock):
            return self._render_list(block)
        elif isinstance(block, CodeBlock):
            return self._render_code(block)
        elif isinstance(block, DividerBlock):
            return UNICODE_DIVIDER
        elif isinstance(block, QuoteBlock):
            return self._render_quote(block)
        elif isinstance(block, ParagraphBlock):
            return self._render_paragraph(block)
        return ""

    def _render_heading(self, block: HeadingBlock) -> str:
        clean = clean_whatsapp_inline(block.text)
        # Level 1 or 2: uppercase bold with accent
        if block.level <= 2:
            return f"*{clean.upper()}*\n{UNICODE_DIVIDER}"
        # Level 3+: Bold capitalized heading
        return f"*{clean}*"

    def _render_table(self, block: TableBlock) -> str:
        """Convert a table into numbered/bulleted cards instead of raw ASCII pipes."""
        if not block.rows:
            return ""

        headers = [clean_whatsapp_inline(h) for h in block.headers]
        cards: List[str] = []

        for idx, row in enumerate(block.rows, 1):
            clean_cells = [clean_whatsapp_inline(c) for c in row]
            if not any(clean_cells):
                continue

            # First column is the title / primary identifier
            title = clean_cells[0] if clean_cells else f"Entry {idx}"
            lines = [f"*{idx}. {title}*"]

            for col_idx in range(1, len(clean_cells)):
                cell_val = clean_cells[col_idx]
                if cell_val:
                    header_label = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else "Details"
                    lines.append(f"• {header_label}: {cell_val}")

            cards.append("\n".join(lines))

        return "\n\n".join(cards)

    def _render_list(self, block: ListBlock) -> str:
        lines: List[str] = []
        for idx, item in enumerate(block.items, 1):
            clean = clean_whatsapp_inline(item.text)
            indent = "  " * item.level

            if block.ordered:
                prefix = f"{idx}. " if item.level == 0 else f"{chr(96 + (idx % 26))}. "
                lines.append(f"{indent}{prefix}{clean}")
            else:
                bullet = "•" if item.level == 0 else ("◦" if item.level == 1 else "▪")
                lines.append(f"{indent}{bullet} {clean}")

        return "\n".join(lines)

    def _render_code(self, block: CodeBlock) -> str:
        code_body = block.code.strip()
        lang_header = f"[{block.language}]\n" if block.language else ""
        return f"```{lang_header}{code_body}```"

    def _render_quote(self, block: QuoteBlock) -> str:
        lines = [f"> {line}" for line in clean_whatsapp_inline(block.text).splitlines()]
        return "\n".join(lines)

    def _render_paragraph(self, block: ParagraphBlock) -> str:
        return clean_whatsapp_inline(block.text)
