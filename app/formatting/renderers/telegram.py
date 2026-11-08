"""Telegram HTML message renderer.

Transforms structured document blocks into Telegram-compliant HTML formatting
(<b>, <i>, <code>, <pre>, <a href="...">) with strict entity escaping and
safe message length splitting.
"""

from __future__ import annotations

import html
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

TELEGRAM_DIVIDER = "──────────────────────────"


VALID_TG_TAGS_REGEX = re.compile(
    r"</?(?:b|strong|i|em|code|pre|s|strike|del|u)\b[^>]*>|<a\s+href=[\"'][^\"']*[\"'][^>]*>|</a>",
    re.IGNORECASE,
)
EXISTING_ENTITY_REGEX = re.compile(r"&(?:lt|gt|amp|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def format_telegram_inline(text: str) -> str:
    """Safely convert markdown inline tokens to Telegram HTML entities, preserving valid HTML tags."""
    if not text:
        return ""

    # First, protect existing markdown links before escaping HTML
    links: List[tuple[str, str]] = []

    def _stash_link(m: re.Match) -> str:
        idx = len(links)
        links.append((m.group(1), m.group(2)))
        return f"@@TG_LINK_{idx}@@"

    stashed = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", _stash_link, text)

    # Protect inline code `code`
    inline_codes: List[str] = []

    def _stash_code(m: re.Match) -> str:
        idx = len(inline_codes)
        inline_codes.append(m.group(1))
        return f"@@TG_CODE_{idx}@@"

    stashed = re.sub(r"`([^`]+)`", _stash_code, stashed)

    # Protect pre-existing valid Telegram HTML tags
    valid_tags: List[str] = []

    def _stash_tag(m: re.Match) -> str:
        idx = len(valid_tags)
        valid_tags.append(m.group(0))
        return f"@@TG_TAG_{idx}@@"

    stashed = VALID_TG_TAGS_REGEX.sub(_stash_tag, stashed)

    # Protect pre-existing HTML entities (&lt;, &gt;, &amp;, etc.)
    entities: List[str] = []

    def _stash_ent(m: re.Match) -> str:
        idx = len(entities)
        entities.append(m.group(0))
        return f"@@TG_ENT_{idx}@@"

    stashed = EXISTING_ENTITY_REGEX.sub(_stash_ent, stashed)

    # Escape HTML special characters in plain text
    escaped = html.escape(stashed, quote=False)

    # Convert bold **text** or __text__ -> <b>text</b>
    escaped = re.sub(r"(?:\*\*|__)(.*?)(?:\*\*|__)", r"<b>\1</b>", escaped)

    # Convert italic *text* or _text_ -> <i>text</i>
    escaped = re.sub(r"(?:(?<=\s)|(?<=^))(?:\*|_)([^*_]+)(?:\*|_)(?=\s|$|[.,!?;:])", r"<i>\1</i>", escaped)

    # Convert strikethrough ~~text~~ -> <s>text</s>
    escaped = re.sub(r"~~(.*?)~~", r"<s>\1</s>", escaped)

    # Restore entities
    for idx, ent in enumerate(entities):
        escaped = escaped.replace(f"@@TG_ENT_{idx}@@", ent)

    # Restore pre-existing valid HTML tags
    for idx, tag in enumerate(valid_tags):
        escaped = escaped.replace(f"@@TG_TAG_{idx}@@", tag)

    # Restore inline code as <code>...</code>
    for idx, code_content in enumerate(inline_codes):
        code_escaped = html.escape(code_content, quote=False)
        escaped = escaped.replace(f"@@TG_CODE_{idx}@@", f"<code>{code_escaped}</code>")

    # Restore links as <a href="...">...</a>
    for idx, (label, url) in enumerate(links):
        label_escaped = html.escape(label, quote=False)
        url_escaped = html.escape(url, quote=True)
        escaped = escaped.replace(
            f"@@TG_LINK_{idx}@@",
            f'<a href="{url_escaped}">{label_escaped}</a>',
        )

    return escaped.strip()


class TelegramRenderer:
    """Renders Document IR into compliant Telegram HTML."""

    def render(self, doc: Document, max_length: int = 4000) -> List[str]:
        """Convert a Document into one or more Telegram HTML message chunks split at block boundaries."""
        chunks: List[str] = []
        current_chunk_blocks: List[str] = []
        current_chunk_len = 0

        for block in doc.blocks:
            rendered = self._render_block(block)
            if not rendered:
                continue

            # If an individual block itself exceeds max_length, flush current chunk and split block
            if len(rendered) > max_length:
                if current_chunk_blocks:
                    chunks.append("\n\n".join(current_chunk_blocks).strip())
                    current_chunk_blocks = []
                    current_chunk_len = 0
                sub_chunks = split_into_chunks(rendered, max_length=max_length)
                chunks.extend(sub_chunks)
                continue

            block_len = len(rendered) + 2  # plus \n\n separator
            if current_chunk_blocks and (current_chunk_len + block_len > max_length):
                chunks.append("\n\n".join(current_chunk_blocks).strip())
                current_chunk_blocks = [rendered]
                current_chunk_len = len(rendered)
            else:
                current_chunk_blocks.append(rendered)
                current_chunk_len += block_len

        if current_chunk_blocks:
            chunks.append("\n\n".join(current_chunk_blocks).strip())

        return chunks or [""]

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
            return f"<code>{TELEGRAM_DIVIDER}</code>"
        elif isinstance(block, QuoteBlock):
            return self._render_quote(block)
        elif isinstance(block, ParagraphBlock):
            return self._render_paragraph(block)
        return ""

    def _render_heading(self, block: HeadingBlock) -> str:
        clean = format_telegram_inline(block.text)
        if block.level <= 2:
            return f"<b>{clean.upper()}</b>\n<code>{TELEGRAM_DIVIDER}</code>"
        return f"<b>{clean}</b>"

    def _render_table(self, block: TableBlock) -> str:
        """Render table rows as clean structured cards avoiding line wrapping."""
        if not block.rows:
            return ""

        headers = [format_telegram_inline(h) for h in block.headers]
        cards: List[str] = []

        for idx, row in enumerate(block.rows, 1):
            clean_cells = [format_telegram_inline(c) for c in row]
            if not any(clean_cells):
                continue

            title = clean_cells[0] if clean_cells else f"Entry {idx}"
            lines = [f"<b>{idx}. {title}</b>"]

            for col_idx in range(1, len(clean_cells)):
                cell_val = clean_cells[col_idx]
                if cell_val:
                    header_label = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else "Details"
                    lines.append(f"• <b>{header_label}:</b> {cell_val}")

            cards.append("\n".join(lines))

        return "\n\n".join(cards)

    def _render_list(self, block: ListBlock) -> str:
        lines: List[str] = []
        for idx, item in enumerate(block.items, 1):
            clean = format_telegram_inline(item.text)
            indent = "  " * item.level

            if block.ordered:
                if item.level == 0:
                    lines.append(f"<b>{idx}. </b>{clean}")
                else:
                    sub_bullet = "◦" if item.level == 1 else "▪"
                    lines.append(f"{indent}{sub_bullet} {clean}")
            else:
                bullet = "•" if item.level == 0 else ("◦" if item.level == 1 else "▪")
                lines.append(f"{indent}{bullet} {clean}")

        return "\n".join(lines)

    def _render_code(self, block: CodeBlock) -> str:
        code_escaped = html.escape(block.code.strip(), quote=False)
        lang_attr = f' class="language-{html.escape(block.language, quote=True)}"' if block.language else ""
        return f"<pre><code{lang_attr}>{code_escaped}</code></pre>"

    def _render_quote(self, block: QuoteBlock) -> str:
        clean = format_telegram_inline(block.text)
        return f"<blockquote>{clean}</blockquote>"

    def _render_paragraph(self, block: ParagraphBlock) -> str:
        return format_telegram_inline(block.text)
