"""Selective deep link extractor and recursive crawler.

Discovers, ranks, and selectively crawls high-relevance internal links from directory
pages, preserving HTML tables as Markdown and aggregating structured multi-page context.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.database.models import ExtractedContent
from app.services.extractor_service import ExtractorService, extractor_service
from app.utils.logging import get_logger

logger = get_logger("app.recursive_crawler")

POSITIVE_KEYWORDS = [
    "hackathon", "event", "competition", "challenge", "register", "registration",
    "details", "apply", "schedule", "track", "venue", "prize", "guidelines",
    "view", "discover", "dates", "agenda", "rules"
]

NEGATIVE_URL_PATTERNS = [
    "/privacy", "/terms", "/cookie", "/login", "/signin", "/signup",
    "/contact", "/about", "/careers", "/jobs", "/press", "/sponsor",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com"
]


@dataclass
class DeepCrawlResult:
    seed_url: str
    seed_content: ExtractedContent
    child_pages: List[ExtractedContent] = field(default_factory=list)
    discovered_links: List[dict] = field(default_factory=list)


def extract_links(html: str, base_url: str) -> List[dict]:
    """Parse anchor tags into absolute URLs and anchor text."""
    soup = BeautifulSoup(html, "html.parser")
    links: List[dict] = []
    seen: Set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = anchor["href"].strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        try:
            full_url = urljoin(base_url, raw_href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue
            clean_url = full_url.split("#")[0].rstrip("/")
            if clean_url in seen:
                continue
            seen.add(clean_url)
            text = anchor.get_text(" ", strip=True)
            links.append({"url": clean_url, "text": text})
        except Exception:
            continue

    return links


def rank_discovered_links(
    links: List[dict],
    base_url: str,
    max_links: int = 4,
    extra_keywords: Optional[List[str]] = None,
) -> List[dict]:
    """Rank discovered links by relevance to events, hackathons, or custom keywords."""
    base_netloc = urlparse(base_url).netloc.lower()
    keywords = POSITIVE_KEYWORDS + (extra_keywords or [])

    scored = []
    for item in links:
        url_lower = item["url"].lower()
        text_lower = item["text"].lower()
        combined = f"{url_lower} {text_lower}"

        # Hard discard on negative utility patterns
        if any(neg in url_lower for neg in NEGATIVE_URL_PATTERNS):
            continue

        score = 0
        for kw in keywords:
            if kw in combined:
                score += 3
        # Same domain bonus
        if urlparse(item["url"]).netloc.lower() == base_netloc:
            score += 2

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_links]]


def table_to_markdown(table_tag) -> str:
    """Convert an HTML <table> into clean GitHub Flavored Markdown."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    md_lines: List[str] = []
    header_col_count = 0

    first_row_cells = rows[0].find_all(["th", "td"])
    if first_row_cells:
        headers = [c.get_text(" ", strip=True) for c in first_row_cells]
        header_col_count = len(headers)
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * header_col_count) + " |")
        rows = rows[1:]

    for tr in rows:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if not cells:
            continue
        if header_col_count:
            if len(cells) < header_col_count:
                cells.extend([""] * (header_col_count - len(cells)))
            elif len(cells) > header_col_count:
                cells = cells[:header_col_count]
        md_lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(md_lines)


class RecursiveCrawler:
    """Manages selective, recursive crawling of directories and detail pages."""

    def __init__(
        self,
        extractor: Optional[ExtractorService] = None,
        max_child_pages: int = 3,
        per_page_timeout: int = 10,
    ) -> None:
        self.extractor = extractor or extractor_service
        self.max_child_pages = max_child_pages
        self.per_page_timeout = per_page_timeout

    def is_directory_page(self, url: str, content: ExtractedContent, links: List[dict]) -> bool:
        """Heuristic check if a page is an event/directory listing."""
        url_lower = url.lower()
        if any(k in url_lower for k in ["/discover", "/allhacks", "/events", "/hackathons", "/competitions", "/browse"]):
            return True
        if len(links) >= 8:
            return True
        return False

    async def deep_crawl(
        self,
        seed_url: str,
        visited_urls: Optional[Set[str]] = None,
        intent_keywords: Optional[List[str]] = None,
    ) -> DeepCrawlResult:
        """Fetch seed page, discover candidate links, and selectively crawl top children."""
        visited = visited_urls if visited_urls is not None else set()
        visited.add(seed_url.rstrip("/"))

        # 1. Fetch seed page
        seed_content = await self.extractor.extract(seed_url)
        if not seed_content.success or not seed_content.markdown:
            return DeepCrawlResult(seed_url=seed_url, seed_content=seed_content)

        # 2. Extract and rank links
        raw_html = seed_content.raw_html or seed_content.markdown or ""
        discovered = extract_links(raw_html, seed_url) if "<a " in raw_html else []
        ranked_links = rank_discovered_links(
            discovered,
            base_url=seed_url,
            max_links=self.max_child_pages,
            extra_keywords=intent_keywords,
        )

        # 3. Filter already visited URLs
        unvisited = [l for l in ranked_links if l["url"].rstrip("/") not in visited]

        # 4. Concurrently crawl top child pages
        child_pages: List[ExtractedContent] = []
        if unvisited and self.is_directory_page(seed_url, seed_content, discovered):
            tasks = [self.extractor.extract(l["url"]) for l in unvisited[: self.max_child_pages]]
            for l in unvisited[: self.max_child_pages]:
                visited.add(l["url"].rstrip("/"))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, ExtractedContent) and res.success and res.markdown:
                    child_pages.append(res)

        return DeepCrawlResult(
            seed_url=seed_url,
            seed_content=seed_content,
            child_pages=child_pages,
            discovered_links=ranked_links,
        )


recursive_crawler = RecursiveCrawler()
