"""Robust Markdown AST parser for structured message formatting."""

from __future__ import annotations

import re
from typing import List, Optional

from app.formatting.models import (
    Block,
    CodeBlock,
    DividerBlock,
    Document,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)
from app.utils.logging import get_logger

logger = get_logger("app.formatting.parser")

HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+)$")
DIVIDER_REGEX = re.compile(r"^(?:---+|\*\*\*+|___+)\s*$")
UNORDERED_LIST_REGEX = re.compile(r"^(\s*)[-\*•]\s+(.+)$")
ORDERED_LIST_REGEX = re.compile(r"^(\s*)(\d+)[\.\)]\s+(.+)$")
TABLE_ROW_REGEX = re.compile(r"^\|(.+)\|\s*$")
TABLE_SEP_REGEX = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")
BLOCKQUOTE_REGEX = re.compile(r"^>\s?(.*)$")


class MarkdownParser:
    """Parses GFM Markdown into structured Block IR with malformed input tolerance."""

    def parse(self, text: str) -> Document:
        """Parse raw markdown text into a Document object."""
        if not text or not text.strip():
            return Document(blocks=[], raw_text=text)

        try:
            return self._parse_lines(text)
        except Exception as exc:
            logger.error("MarkdownParser error: %s; falling back to paragraph chunks", exc)
            # Resilient fallback: split by paragraphs
            blocks: List[Block] = []
            for chunk in text.split("\n\n"):
                clean = chunk.strip()
                if clean:
                    blocks.append(ParagraphBlock(text=clean))
            return Document(blocks=blocks, raw_text=text)

    def _parse_lines(self, text: str) -> Document:
        lines = text.splitlines()
        blocks: List[Block] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()

            # Empty lines
            if not stripped:
                i += 1
                continue

            # 1. Code Block (Fenced)
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                language = stripped[3:].strip()
                code_lines: List[str] = []
                i += 1
                while i < n and not lines[i].strip().startswith(fence):
                    code_lines.append(lines[i])
                    i += 1
                # If closing fence found, advance past it
                if i < n and lines[i].strip().startswith(fence):
                    i += 1
                blocks.append(CodeBlock(language=language, code="\n".join(code_lines)))
                continue

            # 2. Horizontal Rule / Divider
            if DIVIDER_REGEX.match(stripped):
                blocks.append(DividerBlock())
                i += 1
                continue

            # 3. Headings (#, ##, ###, etc.)
            heading_match = HEADING_REGEX.match(stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                blocks.append(HeadingBlock(level=level, text=heading_text))
                i += 1
                continue

            # 4. Table Block (| Col 1 | Col 2 |)
            if stripped.startswith("|") and stripped.endswith("|") and i + 1 < n:
                next_stripped = lines[i + 1].strip()
                if TABLE_SEP_REGEX.match(next_stripped):
                    # Valid table detected
                    header_cells = [c.strip() for c in stripped.split("|")[1:-1]]
                    rows: List[List[str]] = []
                    i += 2  # skip header and separator
                    while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                        row_cells = [c.strip() for c in lines[i].strip().split("|")[1:-1]]
                        # Normalize column count to match headers
                        if len(row_cells) < len(header_cells):
                            row_cells.extend([""] * (len(header_cells) - len(row_cells)))
                        rows.append(row_cells[: len(header_cells)])
                        i += 1
                    blocks.append(TableBlock(headers=header_cells, rows=rows))
                    continue

            # 5. Blockquote (> ...)
            if BLOCKQUOTE_REGEX.match(line):
                quote_lines: List[str] = []
                while i < n and BLOCKQUOTE_REGEX.match(lines[i]):
                    m = BLOCKQUOTE_REGEX.match(lines[i])
                    quote_lines.append(m.group(1).strip() if m else "")
                    i += 1
                blocks.append(QuoteBlock(text="\n".join(quote_lines)))
                continue

            # 6. List Block (Unordered or Ordered)
            unordered_match = UNORDERED_LIST_REGEX.match(line)
            ordered_match = ORDERED_LIST_REGEX.match(line)
            if unordered_match or ordered_match:
                is_ordered = bool(ordered_match)
                list_items: List[ListItem] = []
                while i < n:
                    cur_line = lines[i]
                    cur_u = UNORDERED_LIST_REGEX.match(cur_line)
                    cur_o = ORDERED_LIST_REGEX.match(cur_line)
                    if cur_u:
                        indent = len(cur_u.group(1))
                        level = indent // 2 if indent >= 2 else 0
                        list_items.append(ListItem(text=cur_u.group(2).strip(), level=level, index=None))
                        i += 1
                    elif cur_o:
                        indent = len(cur_o.group(1))
                        level = indent // 2 if indent >= 2 else 0
                        idx = int(cur_o.group(2))
                        list_items.append(ListItem(text=cur_o.group(3).strip(), level=level, index=idx))
                        i += 1
                    elif cur_line.startswith("   ") or cur_line.startswith("\t"):
                        # Continuation of previous list item
                        if list_items:
                            list_items[-1].text += " " + cur_line.strip()
                        i += 1
                    else:
                        break
                blocks.append(ListBlock(items=list_items, ordered=is_ordered))
                continue

            # 7. Paragraph (accumulate until blank line or another block start)
            para_lines: List[str] = [stripped]
            i += 1
            while i < n:
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if (
                    HEADING_REGEX.match(next_stripped)
                    or DIVIDER_REGEX.match(next_stripped)
                    or next_stripped.startswith("```")
                    or next_stripped.startswith("~~~")
                    or (next_stripped.startswith("|") and next_stripped.endswith("|"))
                    or UNORDERED_LIST_REGEX.match(next_line)
                    or ORDERED_LIST_REGEX.match(next_line)
                    or BLOCKQUOTE_REGEX.match(next_line)
                ):
                    break
                para_lines.append(next_stripped)
                i += 1
            blocks.append(ParagraphBlock(text="\n".join(para_lines)))

        return Document(blocks=blocks, raw_text=text)
