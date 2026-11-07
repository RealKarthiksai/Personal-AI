"""Base renderer interface and safe message splitting utilities."""

from __future__ import annotations

from typing import List, Protocol

from app.formatting.models import Document


class BaseRenderer(Protocol):
    """Protocol for platform-specific document renderers."""

    def render(self, doc: Document, max_length: int = 4000) -> List[str]:
        """Convert a Document into one or more platform-formatted message chunks."""
        ...


def split_into_chunks(text: str, max_length: int = 4000) -> List[str]:
    """Split text into chunks under max_length, preserving section and paragraph boundaries."""
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    def _split_long_line(line: str) -> List[str]:
        res: List[str] = []
        while len(line) > max_length:
            split_idx = line.rfind(" ", 0, max_length)
            if split_idx <= 0:
                split_idx = max_length
            res.append(line[:split_idx].strip())
            line = line[split_idx:].strip()
        if line:
            res.append(line)
        return res

    chunks: List[str] = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for p in paragraphs:
        p_str = p.strip()
        if not p_str:
            continue

        # If adding p_str to current_chunk fits, append it
        if current_chunk and len(current_chunk) + len(p_str) + 2 <= max_length:
            current_chunk += "\n\n" + p_str
            continue

        # Otherwise, flush current_chunk if present
        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

        # Now handle p_str alone
        if len(p_str) <= max_length:
            current_chunk = p_str
        else:
            # Paragraph itself exceeds max_length: split by lines
            lines = p_str.split("\n")
            for line in lines:
                sub_chunks = _split_long_line(line) if len(line) > max_length else [line]
                for sc in sub_chunks:
                    if not sc.strip():
                        continue
                    if not current_chunk:
                        current_chunk = sc
                    elif len(current_chunk) + len(sc) + 1 <= max_length:
                        current_chunk += "\n" + sc
                    else:
                        chunks.append(current_chunk)
                        current_chunk = sc

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text[:max_length]]
