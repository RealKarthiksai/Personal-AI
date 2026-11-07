"""Grounding Verifier and URL Normalization Engine.

Protects against entity and URL hallucination in GROUNDED_TEXT mode by validating
all links, domains, and references against an allow-list of retrieved source URLs.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import FrozenSet, List, Optional, Set

from app.utils.logging import get_logger

logger = get_logger("app.grounding_verifier")

# Tracking parameters to strip during URL normalization
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_eid",
}

# Regex to match URLs in generated text (with scheme or scheme-less domains)
URL_FINDER_REGEX = re.compile(
    r"(?:https?://[^\s<>\"'()]+|(?:github\.com|arxiv\.org|huggingface\.co|reddit\.com|openalex\.org)/[^\s<>\"'()]+)",
    re.IGNORECASE,
)


def normalize_url(url: str) -> str:
    """Normalize a URL for canonical allow-list comparison.

    Rules:
    - Force https scheme.
    - Lowercase hostname and strip 'www.'.
    - Drop default ports (:80, :443).
    - Drop tracking parameters (utm_*, fbclid, gclid).
    - Drop URL fragments (#...).
    - Strip trailing slashes from path (unless path is empty).
    - Preserve path casing and non-tracking query parameters.
    """
    clean = url.strip()
    if not clean.startswith("http://") and not clean.startswith("https://"):
        clean = "https://" + clean

    try:
        parsed = urllib.parse.urlsplit(clean)
    except Exception:
        return clean.lower()

    # Host normalization
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove default ports
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Path normalization (preserve case, strip trailing slash if length > 1)
    path = parsed.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Query normalization (filter out tracking parameters)
    filtered_query = ""
    if parsed.query:
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        clean_pairs = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS]
        clean_pairs.sort(key=lambda x: x[0])
        if clean_pairs:
            filtered_query = urllib.parse.urlencode(clean_pairs)

    # Always enforce https scheme and drop fragment
    return urllib.parse.urlunsplit(("https", netloc, path, filtered_query, ""))


def extract_all_urls(text: str) -> List[str]:
    """Extract all URLs and prominent scheme-less platform URLs from text."""
    matches = URL_FINDER_REGEX.findall(text)
    cleaned = []
    for m in matches:
        clean = m.rstrip(".,;:!?)'\"")
        if clean:
            cleaned.append(clean)
    return cleaned


def validate_grounded_text(text: str, allowed_urls: FrozenSet[str]) -> str:
    """Validate that all URLs in the generated text exist in the allow-list.

    If an ungrounded or fabricated URL is found, the containing sentence or link
    is stripped to prevent misleading claims from reaching the user.
    """
    if not text or not allowed_urls:
        return text

    # Pre-normalize the allow-list
    normalized_allowed: Set[str] = {normalize_url(u) for u in allowed_urls if u}

    # Split into sentences or lines to sanitize accurately
    lines = text.split("\n")
    clean_lines: List[str] = []

    for line in lines:
        urls_in_line = extract_all_urls(line)
        if not urls_in_line:
            clean_lines.append(line)
            continue

        line_valid = True
        sanitized_line = line

        for raw_u in urls_in_line:
            norm_u = normalize_url(raw_u)
            if norm_u not in normalized_allowed:
                # Disallowed URL found! Check if host at least matches an allowed host
                raw_host = urllib.parse.urlsplit(norm_u).netloc
                allowed_hosts = {urllib.parse.urlsplit(a).netloc for a in normalized_allowed}

                logger.warning(
                    "Ungrounded URL blocked: %r (normalized: %r, allowed_hosts: %r)",
                    raw_u,
                    norm_u,
                    allowed_hosts,
                )

                # Remove the markdown link [text](url) -> text or strip URL
                link_pattern = re.compile(r"\[([^\]]+)\]\(" + re.escape(raw_u) + r"\)")
                if link_pattern.search(sanitized_line):
                    sanitized_line = link_pattern.sub(r"\1", sanitized_line)
                else:
                    sanitized_line = sanitized_line.replace(raw_u, "").strip()

        if sanitized_line.strip():
            clean_lines.append(sanitized_line)

    return "\n".join(clean_lines)
