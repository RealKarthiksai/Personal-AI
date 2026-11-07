"""Intelligent tool router for connecting the local LLM to search & web extraction.

Analyzes incoming messages to determine if web search or page reading is required,
executes the necessary tool, and injects clean context into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from app.services.extractor_service import ExtractorService, extractor_service
from app.services.planner_service import PlannerService, planner_service
from app.services.query_normalizer import normalize_query
from app.services.recursive_crawler import RecursiveCrawler, recursive_crawler
from app.services.search_service import SearchService, search_service
from app.services.source_verifier import SourceVerifier
from app.services.structured_extractor import StructuredExtractor
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
    r".*\b(?:latest\s+version\s+of|recent\s+news\s+about|release\s+date\s+of)\s+(.+)",
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
        crawler_svc: Optional[RecursiveCrawler] = None,
        structured_extractor: Optional[StructuredExtractor] = None,
        source_verifier: Optional[SourceVerifier] = None,
        planner_svc: Optional[PlannerService] = None,
    ) -> None:
        self.search = search_svc or search_service
        self.extractor = extractor_svc or extractor_service
        self.crawler = crawler_svc or recursive_crawler
        self.structured_extractor = structured_extractor or StructuredExtractor()
        self.source_verifier = source_verifier or SourceVerifier()
        self.planner = planner_svc or planner_service



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

                # Attempt structured event extraction if relevant
                if extracted.success and extracted.markdown:
                    entities = await self.structured_extractor.extract_hackathons(
                        extracted.markdown,
                        source_url=target_url,
                        use_model_fallback=False,
                    )
                    if entities:
                        verified = self.source_verifier.verify_and_score(entities)
                        struct_md = self.structured_extractor.format_for_llm(verified)
                        context = f"{struct_md}\n\n{context}"

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

        # 2. Search intent & plan generation via PlannerService
        plan = await self.planner.plan_tasks(clean_text, previous_query=previous_query)
        if plan.requires_search and plan.search_queries:
            status_msg = f"🔍 Researching: {plan.task_summary}..."
            logger.info("ToolRouter: executing plan | task=%r | queries=%r", plan.task_summary, plan.search_queries)
            try:
                import asyncio

                # Execute all planned search queries concurrently
                tasks = [self.search.search(q) for q in plan.search_queries]
                search_results_list = await asyncio.gather(*tasks, return_exceptions=True)

                results = []
                seen_urls = set()
                for res in search_results_list:
                    if isinstance(res, list):
                        for r in res:
                            if r.url and r.url not in seen_urls:
                                results.append(r)
                                seen_urls.add(r.url)

                search_context = self.search.format_for_llm(results[:8])

                # 3. Deep crawl & Structured Extraction for event/hackathon queries
                combined_query_str = (plan.task_summary + " " + " ".join(plan.search_queries)).lower()
                is_event_query = any(
                    k in combined_query_str
                    for k in ("hackathon", "hackathons", "competition", "event", "events", "meetup")
                )
                if is_event_query and results:
                    candidate_urls = [r.url for r in results[:2] if r.url]
                    extracted_events = []
                    intent_keywords = [
                        w.lower() for w in re.split(r"\W+", plan.task_summary) if len(w) > 2
                    ]
                    for cand_url in candidate_urls:
                        try:
                            crawl_bundle = await self.crawler.deep_crawl(
                                cand_url,
                                intent_keywords=intent_keywords,
                            )
                            if crawl_bundle.seed_content and crawl_bundle.seed_content.markdown:
                                events = await self.structured_extractor.extract_hackathons(
                                    crawl_bundle.seed_content.markdown,
                                    source_url=crawl_bundle.seed_url,
                                    use_model_fallback=False,
                                )
                                extracted_events.extend(events)
                            for child in crawl_bundle.child_pages:
                                if child.markdown:
                                    child_events = await self.structured_extractor.extract_hackathons(
                                        child.markdown,
                                        source_url=child.url,
                                        use_model_fallback=False,
                                    )
                                    extracted_events.extend(child_events)
                        except Exception as crawl_exc:
                            logger.warning("Deep crawl error for %s: %s", cand_url, crawl_exc)

                    if extracted_events:
                        filter_expired = any(w in clean_text.lower() for w in ("this month", "upcoming", "now", "today", "current"))
                        verified_events = self.source_verifier.verify_and_score(
                            extracted_events,
                            filter_expired=filter_expired,
                        )
                        if verified_events:
                            struct_md = self.structured_extractor.format_for_llm(verified_events)
                            search_context = f"{struct_md}\n\n### Web Sources:\n{search_context}"

                # Prepend task plan summary to context
                req_details_str = ", ".join(plan.required_details) if plan.required_details else "Factual details and links"
                research_plan_header = (
                    f"### Research Plan:\n"
                    f"- Objective: {plan.task_summary}\n"
                    f"- Required Attributes: {req_details_str}"
                )
                search_context = f"{research_plan_header}\n\n{search_context}"

                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=plan.task_summary,
                    context_text=search_context,
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter search execution failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=plan.task_summary,
                    context_text=f"Web search unavailable: {exc}",
                    status_message=status_msg,
                )

        # 4. Direct pass-through (no tool needed)
        return ToolExecutionResult(
            tool_name=None,
            input_value=None,
            context_text=None,
            status_message=None,
        )



tool_router = ToolRouter()
