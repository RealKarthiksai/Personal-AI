"""Unit tests for PlannerService."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.planner_service import PlannerService, SearchPlan


@pytest.mark.asyncio
async def test_planner_model_success():
    mock_llm = MagicMock()
    plan_json = json.dumps({
        "requires_search": True,
        "task_summary": "Find hackathons in Hyderabad for November 2026",
        "search_queries": [
            "hackathons in hyd this month",
            "tech competitions Hyderabad Unstop"
        ],
        "required_details": ["dates", "venue", "prizes", "links"]
    })
    mock_llm.generate = AsyncMock(return_value=plan_json)

    planner = PlannerService(llm_client=mock_llm)
    plan = await planner.plan_tasks("can you find hackathons in hyd this month")

    assert plan.requires_search is True
    assert "Hyderabad" in plan.task_summary
    assert len(plan.search_queries) == 2
    # Verify normalization occurred on queries ("hyd" -> "Hyderabad")
    assert "Hyderabad" in plan.search_queries[0]
    assert "dates" in plan.required_details


@pytest.mark.asyncio
async def test_planner_fallback_on_invalid_json():
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="Sorry I cannot output JSON right now.")

    planner = PlannerService(llm_client=mock_llm)
    # The user asks an event question that definitely needs search
    plan = await planner.plan_tasks("hackathons in hyd this month")

    # Should fall back gracefully to rule-based normalizer
    assert plan.requires_search is True
    assert len(plan.search_queries) >= 1
    assert any("Hyderabad" in q for q in plan.search_queries)


@pytest.mark.asyncio
async def test_planner_casual_conversation():
    mock_llm = MagicMock()
    plan_json = json.dumps({
        "requires_search": False,
        "task_summary": "Greeting",
        "search_queries": [],
        "required_details": []
    })
    mock_llm.generate = AsyncMock(return_value=plan_json)

    planner = PlannerService(llm_client=mock_llm)
    plan = await planner.plan_tasks("Hello! How are you today?")

    assert plan.requires_search is False
    assert len(plan.search_queries) == 0


@pytest.mark.asyncio
async def test_planner_direct_url():
    planner = PlannerService()
    plan = await planner.plan_tasks("https://example.com/blog/article")

    assert plan.requires_search is False
    assert "example.com" in plan.task_summary
