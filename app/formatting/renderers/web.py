"""Web Markdown renderer.

Preserves rich GitHub-Flavored Markdown (GFM) intact for web clients,
including headings, tables, links, quotes, and code blocks.
"""

from __future__ import annotations

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


class WebRenderer:
    """Renders Document IR or raw markdown into clean standard GFM Markdown."""

    def render(self, doc: Document, max_length: int = 4000) -> List[str]:
        """Convert a Document into standard Markdown message chunks."""
        # If raw text was captured and unmodified, preserve it with 100% fidelity
        if doc.raw_text is not None:
            return split_into_chunks(doc.raw_text.strip(), max_length=max_length)

        sections: List[str] = []
        for block in doc.blocks:
            rendered = self._render_block(block)
            if rendered:
                sections.append(rendered)

        full_text = "\n\n".join(sections).strip()
        return split_into_chunks(full_text, max_length=max_length)

    def _render_block(self, block: Block) -> str:
        if isinstance(block, HeadingBlock):
            prefix = "#" * max(1, min(block.level, 6))
            return f"{prefix} {block.text}"
        elif isinstance(block, TableBlock):
            return self._render_table(block)
        elif isinstance(block, ListBlock):
            return self._render_list(block)
        elif isinstance(block, CodeBlock):
            lang = block.language or ""
            return f"```{lang}\n{block.code}\n```"
        elif isinstance(block, DividerBlock):
            return "---"
        elif isinstance(block, QuoteBlock):
            return "\n".join(f"> {line}" for line in block.text.splitlines())
        elif isinstance(block, ParagraphBlock):
            return block.text
        return ""

    def _render_table(self, block: TableBlock) -> str:
        if not block.headers and not block.rows:
            return ""

        headers = block.headers
        lines: List[str] = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in block.rows:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _render_list(self, block: ListBlock) -> str:
        lines: List[str] = []
        for idx, item in enumerate(block.items, 1):
            indent = "  " * item.level
            if block.ordered:
                prefix = f"{idx}. "
                lines.append(f"{indent}{prefix}{item.text}")
            else:
                lines.append(f"{indent}- {item.text}")
        return "\n".join(lines)
