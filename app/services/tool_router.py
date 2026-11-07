"""Intelligent tool router for connecting the local LLM to search & web extraction.

Analyzes incoming messages to determine if web search or page reading is required,
executes the necessary tool, and injects clean context into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from app.services.extractor_service import ExtractorService, extractor_service
from app.services.search_service import SearchService, search_service
from app.utils.logging import get_logger

logger = get_logger("app.tool_router")

# Regex to match URLs in messages
URL_REGEX = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)

# Patterns that indicate search or real-time intent
SEARCH_PATTERNS = [
    # Explicit search / find prefixes: "can you find ...", "please search ...", "find all ..."
    r"^(?:can\s+you\s+|could\s+you\s+|please\s+|help\s+me\s+)?(?:find|search|look\s*up|google|check|get|tell\s+me\s+about|show\s+me)\s+(?:for\s+|out\s+)?(.+)",
    # Questions about current events, scores, weather, people, dates
    r"^(?:what\s+(?:is|are)\s+the\s+latest|who\s+won|what\s+happened\s+with|current\s+price\s+of|weather\s+in|news\s+about)\s+(.+)",
    r".*\b(?:latest\s+version\s+of|recent\s+news\s+about|release\s+date\s+of|upcoming\s+events\s+in|hackathons\s+in)\s+(.+)",
    r".*\b(?:search\s+the\s+web\s+for|search\s+online\s+for|search\s+for)\s+(.+)",
]

# Follow-up requests that refer back to the prior turn: "use searching", "search it", "google it"
FOLLOWUP_PATTERNS = [
    r"^(?:use\s+searching|use\s+search|search\s+that|search\s+it|search\s+again|google\s+it|look\s+it\s+up|search|try\s+searching|browse\s+the\s+web|look\s+online)[\s\.\?!]*$",
]

# Real-time event/live knowledge keywords: if found alongside location/time qualifiers
REALTIME_KEYWORDS = [
    r"\b(?:hackathon|hackathons|conference|conferences|meetup|meetups|webinar|webinars)\b",
    r"\b(?:weather|forecast|stock\s+price|live\s+score|breaking\s+news|ticket\s+booking)\b",
    r"\b(?:upcoming\s+events|events\s+happening|happening\s+in)\b",
]


@dataclass
class ToolExecutionResult:
    tool_name: Optional[str]
    input_value: Optional[str]
    context_text: Optional[str]
    status_message: Optional[str]


class ToolRouter:
    """Routes messages to search/extraction tools or passes through directly."""

    def __init__(
        self,
        search_svc: Optional[SearchService] = None,
        extractor_svc: Optional[ExtractorService] = None,
    ) -> None:
        self.search = search_svc or search_service
        self.extractor = extractor_svc or extractor_service

    def extract_urls(self, text: str) -> List[str]:
        """Extract HTTP/HTTPS URLs from the input text."""
        return URL_REGEX.findall(text)

    def detect_search_query(
        self,
        text: str,
        previous_query: Optional[str] = None,
    ) -> Optional[str]:
        """Determine if text expresses explicit, topical, or follow-up search intent."""
        stripped = text.strip()

        # 1. Handle explicit /search command
        if stripped.lower().startswith("/search"):
            parts = stripped.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
            if previous_query:
                return previous_query.strip()
            return None

        # 2. Check for followup patterns like "use searching", "search it"
        for pattern in FOLLOWUP_PATTERNS:
            if re.search(pattern, stripped, re.IGNORECASE):
                if previous_query:
                    return previous_query.strip()

        # 3. Check explicit search / question patterns
        for pattern in SEARCH_PATTERNS:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                return query.rstrip("?.! ")

        # 4. Check real-time event / live knowledge keywords
        for pattern in REALTIME_KEYWORDS:
            if re.search(pattern, stripped, re.IGNORECASE):
                return stripped.rstrip("?.! ")

        return None

    def detect_read_url(self, text: str) -> Optional[str]:
        """Determine if text requests reading or summarizing a URL."""
        stripped = text.strip()

        # Handle explicit /read command
        if stripped.lower().startswith("/read"):
            parts = stripped.split(maxsplit=1)
            if len(parts) > 1:
                urls = self.extract_urls(parts[1])
                return urls[0] if urls else parts[1].strip()

        urls = self.extract_urls(stripped)
        if urls:
            return urls[0]

        return None

    async def route_and_execute(
        self,
        user_message: str,
        previous_query: Optional[str] = None,
    ) -> ToolExecutionResult:
        """Analyze message, execute appropriate tool if needed, and return context."""
        clean_text = user_message.strip()

        # 1. URL extraction check (highest priority if URL present)
        target_url = self.detect_read_url(clean_text)
        if target_url:
            logger.info("ToolRouter: routing to ExtractorService | url=%r", target_url)
            status_msg = f"📄 Reading webpage: {target_url}..."
            try:
                extracted = await self.extractor.extract(target_url)
                context = self.extractor.format_for_llm(extracted)
                return ToolExecutionResult(
                    tool_name="web_extractor",
                    input_value=target_url,
                    context_text=context,
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter extractor failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="web_extractor",
                    input_value=target_url,
                    context_text=f"Failed to read webpage {target_url}: {exc}",
                    status_message=status_msg,
                )

        # 2. Search intent check
        search_query = self.detect_search_query(clean_text, previous_query=previous_query)
        if search_query:
            logger.info("ToolRouter: routing to SearchService | query=%r", search_query)
            status_msg = f"🔍 Searching the web for: {search_query}..."
            try:
                results = await self.search.search(search_query)
                context = self.search.format_for_llm(results)
                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=search_query,
                    context_text=context,
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter search failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=search_query,
                    context_text=f"Web search unavailable: {exc}",
                    status_message=status_msg,
                )

        # 3. Direct pass-through (no tool needed)
        return ToolExecutionResult(
            tool_name=None,
            input_value=None,
            context_text=None,
            status_message=None,
        )


tool_router = ToolRouter()
