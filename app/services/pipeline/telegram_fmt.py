"""Phase 5: Telegram HTML formatting, AI filler scrubbing, and chunking."""
from __future__ import annotations

import html
import re
from typing import Dict, List

AI_TELLS = [
    r"^(sure|certainly|of course|absolutely|great question)[,!.]\s*",
    r"\bas an ai\b[^.]*\.\s*",
    r"\bi hope this helps\b[^.]*\.?",
    r"\blet me know if you (need|have)[^.]*\.?",
]


def format_reply(text: str, pages: List[Dict[str, str]]) -> str:
    """Format raw model output into clean Telegram-compliant HTML with sources."""
    if not text:
        return ""

    # 1. Scrub AI assistant tell phrases
    for pat in AI_TELLS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # 2. Convert markdown headers to bold or clean text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 3. Detect and stash source citation tags [1], [2] before escaping HTML
    used_numbers = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
    text = re.sub(r"\s*\[\d+\]", "", text)

    # 4. Escape HTML to prevent broken entity rendering
    text = html.escape(text.strip())

    # 5. Convert markdown formatting to safe Telegram HTML
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # 6. Append clickable source links if citations were referenced
    if used_numbers and pages:
        links: List[str] = []
        for n in used_numbers:
            if 1 <= n <= len(pages):
                url = html.escape(pages[n - 1]["url"])
                links.append(f'<a href="{url}">{n}</a>')
        if links:
            text += "\n\n<i>Sources:</i> " + " • ".join(links)

    return text.strip()


def chunks(text: str, limit: int = 3500) -> List[str]:
    """Split text into message chunks by double newlines without breaking HTML blocks."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    out: List[str] = []
    cur = ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > limit and cur:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para

    if cur:
        out.append(cur)
    return out
