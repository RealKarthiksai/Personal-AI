"""Task and Search Planner service.

Deconstructs user queries using the local LLM to understand required tasks,
identify missing information, and generate a concrete search plan before execution.
Includes robust rule-based fallback if the local LLM returns malformed JSON.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from app.context.temporal import get_temporal_context
from app.services.llm_client import LLMClient
from app.services.query_normalizer import normalize_query
from app.utils.logging import get_logger

logger = get_logger("app.planner_service")


class SearchPlan(BaseModel):
    requires_search: bool = Field(default=False, description="Whether web search is required")
    task_summary: str = Field(default="", description="1-sentence summary of what needs to be accomplished")
    search_queries: List[str] = Field(default_factory=list, description="Specific search queries to execute")
    required_details: List[str] = Field(default_factory=list, description="Attributes/data points to extract")


class PlannerService:
    """Understands user queries and creates an actionable search and retrieval plan."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm = llm_client or LLMClient()

    async def plan_tasks(
        self,
        user_message: str,
        previous_query: Optional[str] = None,
    ) -> SearchPlan:
        """Analyze message, understand objectives, and generate an execution plan."""
        clean_text = user_message.strip()
        temp_ctx = get_temporal_context()

        # If previous query exists and user says "use searching" / "search it"
        effective_text = clean_text
        if re.search(r"^(?:use\s+searching|use\s+search|search\s+it|search\s+that|google\s+it)[\s\.\?!]*$", clean_text, re.I):
            if previous_query:
                effective_text = previous_query.strip()

        # Direct URL check: if text is a URL, search is not required (direct extract)
        if re.search(r"^https?://[^\s]+$", effective_text):
            return SearchPlan(
                requires_search=False,
                task_summary=f"Read webpage at {effective_text}",
                search_queries=[],
                required_details=["page summary", "key content"],
            )

        prompt = (
            f"Today is {temp_ctx['day']}, {temp_ctx['month']} {temp_ctx['day']}, {temp_ctx['year']} "
            f"(Date: {temp_ctx['current_date']}, Timezone: {temp_ctx['timezone']}).\n"
            f"User Request: {effective_text}\n\n"
            "Analyze the user request. Does it require external web search or live information "
            "(e.g. current events, hackathons, news, weather, release dates, factual lookups)?\n"
            "Respond ONLY with a JSON object in this exact schema without preamble or markdown:\n"
            "{\n"
            '  "requires_search": true,\n'
            '  "task_summary": "Find hackathons in Hyderabad for current month",\n'
            '  "search_queries": [\n'
            '    "hackathons in Hyderabad November 2026",\n'
            '    "tech competitions and hackathons Hyderabad 2026 Unstop Devfolio"\n'
            "  ],\n"
            '  "required_details": ["event dates", "location", "registration deadline", "prize pool", "links"]\n'
            "}\n"
            "If the request is general chatter, greeting, math, or self-contained reasoning that does NOT need search:\n"
            "{\n"
            '  "requires_search": false,\n'
            '  "task_summary": "General conversational response",\n'
            '  "search_queries": [],\n'
            '  "required_details": []\n'
            "}"
        )

        try:
            resp = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You are a factual AI task planner. Output valid JSON only.",
                max_tokens=180,
                temperature=0.1,
            )
            raw = resp.strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw[start : end + 1])
                plan = SearchPlan(
                    requires_search=bool(data.get("requires_search", False)),
                    task_summary=str(data.get("task_summary", "")),
                    search_queries=[str(q).strip() for q in data.get("search_queries", []) if str(q).strip()],
                    required_details=[str(d).strip() for d in data.get("required_details", []) if str(d).strip()],
                )
                if plan.requires_search and plan.search_queries:
                    # Normalize each search query for location and date accuracy
                    norm_queries = []
                    for q in plan.search_queries[:3]:
                        n = normalize_query(q)
                        norm_queries.append(n.normalized)
                    plan.search_queries = norm_queries
                    return plan
        except Exception as exc:
            logger.warning("Planner LLM generation/parsing failed: %s", exc)

        # Fallback to rule-based normalizer
        norm_res = normalize_query(effective_text)
        is_search = (
            norm_res.intent in ("events", "news", "research")
            or any(k in effective_text.lower() for k in ("search", "find", "latest", "upcoming", "hackathon", "weather", "who won", "news", "price"))
        )

        if is_search:
            queries = [norm_res.normalized]
            if norm_res.expanded_queries:
                queries.extend(norm_res.expanded_queries[:2])
            # Deduplicate
            seen = set()
            clean_queries = []
            for q in queries:
                if q not in seen:
                    clean_queries.append(q)
                    seen.add(q)

            return SearchPlan(
                requires_search=True,
                task_summary=f"Search for {norm_res.normalized}",
                search_queries=clean_queries[:3],
                required_details=["dates", "details", "links"],
            )

        return SearchPlan(
            requires_search=False,
            task_summary="Conversational response",
            search_queries=[],
            required_details=[],
        )


planner_service = PlannerService()
