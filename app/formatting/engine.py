"""Cross-Platform Message Formatting Engine.

Routes raw AI markdown responses through the AST parser and selects the appropriate
platform renderer (WhatsApp, Telegram, Web) with resilient fallback protection.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.formatting.models import Document
from app.formatting.parser import MarkdownParser
from app.formatting.renderers.base import BaseRenderer, split_into_chunks
from app.formatting.renderers.telegram import TelegramRenderer
from app.formatting.renderers.web import WebRenderer
from app.formatting.renderers.whatsapp import WhatsAppRenderer
from app.utils.logging import get_logger

logger = get_logger("app.formatting.engine")

DEFAULT_MAX_LENGTHS: Dict[str, int] = {
    "telegram": 4000,
    "whatsapp": 4000,
    "web": 32000,
}


def _strip_broken_markdown(text: str) -> str:
    """Fallback sanitizer to remove markdown artifacts that break messaging UIs."""
    if not text:
        return ""
    # Strip markdown headers (# Title -> Title)
    s = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)
    # Strip horizontal rules (--- or ***)
    s = re.sub(r"^(?:---+|\*\*\*+|___+)\s*$", "", s, flags=re.MULTILINE)
    # Convert [text](url) -> text (url)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", r"\1 (\2)", s)
    # Convert table rows (| a | b |) by replacing pipes with commas/spaces
    def _clean_table_row(m: re.Match) -> str:
        row = m.group(0).strip("|")
        cells = [c.strip() for c in row.split("|") if c.strip() and not set(c.strip()).issubset({"-", ":"})]
        return " • ".join(cells) if cells else ""

    s = re.sub(r"^\|(.+)\|$", _clean_table_row, s, flags=re.MULTILINE)
    # Compress consecutive blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class MessageFormattingEngine:
    """Core engine orchestrating parsing and platform-specific message rendering."""

    def __init__(self) -> None:
        self.parser = MarkdownParser()
        self.renderers: Dict[str, BaseRenderer] = {
            "whatsapp": WhatsAppRenderer(),
            "telegram": TelegramRenderer(),
            "web": WebRenderer(),
        }

    def format_message(
        self,
        text: str,
        channel: str = "web",
        max_length: Optional[int] = None,
    ) -> List[str]:
        """Format an AI response for the target channel.

        Args:
            text: Raw markdown output from AI generation.
            channel: Target messaging platform ('whatsapp', 'telegram', 'web').
            max_length: Optional chunk character limit. Defaults to platform limits.

        Returns:
            List of formatted message chunks ready for transmission.
        """
        norm_channel = (channel or "web").lower().strip()
        effective_max = max_length or DEFAULT_MAX_LENGTHS.get(norm_channel, 4000)

        logger.info(
            "MessageFormattingEngine: formatting message | channel=%s | input_length=%d | max_chunk=%d",
            norm_channel,
            len(text) if text else 0,
            effective_max,
        )

        if not text or not text.strip():
            return []

        renderer = self.renderers.get(norm_channel)
        if not renderer:
            logger.warning(
                "MessageFormattingEngine: unrecognized channel '%s', falling back to web renderer",
                norm_channel,
            )
            renderer = self.renderers["web"]

        try:
            document = self.parser.parse(text)
            chunks = renderer.render(document, max_length=effective_max)
            if chunks:
                return chunks
        except Exception as exc:
            logger.error(
                "MessageFormattingEngine error during render: %s; falling back to sanitized text",
                exc,
                exc_info=True,
            )

        # Fallback handling
        fallback_text = _strip_broken_markdown(text)
        return split_into_chunks(fallback_text, max_length=effective_max)


# Global singleton instance
formatting_engine = MessageFormattingEngine()
