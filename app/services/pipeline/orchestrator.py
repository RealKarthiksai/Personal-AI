"""Multi-stage pipeline orchestrator connecting planner, search, synth, persona, and formatting."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple, Union
from app.services.pipeline import fetcher, persona, planner, synth
from app.services.pipeline.telegram_fmt import chunks, format_reply
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.orchestrator")


async def answer_pipeline(
    user_msg: str,
    history: List[Tuple[str, str]],
    memory_facts: List[str],
    include_metadata: bool = False,
) -> Union[List[str], Tuple[List[str], Dict[str, Any]]]:
    """Execute the multi-stage LLM pipeline. Returns a list of formatted message chunks,

    and optionally a metadata dict containing per-stage timings and execution details.
    """
    logger.info("Executing multi-stage pipeline for message: %r", user_msg[:60])
    t0 = time.perf_counter()
    timings: Dict[str, float] = {
        "planner_ms": 0.0,
        "fetch_ms": 0.0,
        "synth_ms": 0.0,
        "persona_ms": 0.0,
        "total_ms": 0.0,
    }
    meta: Dict[str, Any] = {
        "path": "pipeline-unknown",
        "timings": timings,
        "queries": [],
        "pages_count": 0,
        "failed_stage": None,
    }

    # 1. Plan
    t_plan_start = time.perf_counter()
    plan_data = await planner.plan(user_msg, history)
    timings["planner_ms"] = round((time.perf_counter() - t_plan_start) * 1000, 1)

    needs_search = plan_data.get("needs_search", False)
    queries = plan_data.get("queries", [])
    context = plan_data.get("context", "")
    meta["queries"] = queries

    # Fast path: Casual chat or self-contained logic (0 search latency)
    if not needs_search or not queries:
        logger.info("Pipeline fast path (no search needed)")
        meta["path"] = "pipeline-fast"
        t_persona_start = time.perf_counter()
        reply = await persona.reply_direct(user_msg, history, memory_facts)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res_chunks = chunks(format_reply(reply, []))
        return (res_chunks, meta) if include_metadata else res_chunks

    # 2. Search & Fetch in parallel
    logger.info("Pipeline search path with queries: %s", queries)
    meta["path"] = "pipeline-search"
    t_fetch_start = time.perf_counter()
    pages = await fetcher.gather(queries)
    timings["fetch_ms"] = round((time.perf_counter() - t_fetch_start) * 1000, 1)
    meta["pages_count"] = len(pages)
    meta["pages"] = [{"title": p.get("title", ""), "url": p.get("url", "")} for p in pages]

    if not pages:
        logger.info("Pipeline search yielded 0 pages; answering in character")
        meta["path"] = "pipeline-search-empty"
        t_persona_start = time.perf_counter()
        fallback_msg = f"{user_msg}\n(I couldn't find any relevant results online; say so in character.)"
        reply = await persona.reply_direct(fallback_msg, history, memory_facts)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res_chunks = chunks(format_reply(reply, []))
        return (res_chunks, meta) if include_metadata else res_chunks

    # 3. Synthesize & Rewrite
    try:
        t_synth_start = time.perf_counter()
        draft = await synth.synthesize(user_msg, context, pages)
        timings["synth_ms"] = round((time.perf_counter() - t_synth_start) * 1000, 1)
    except Exception as exc:
        logger.warning("Pipeline synthesis error: %s; falling back to top snippet", exc)
        meta["failed_stage"] = "synth"
        draft = pages[0]["text"][:400]

    try:
        t_persona_start = time.perf_counter()
        final = await persona.rewrite(draft, user_msg)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
    except Exception as exc:
        logger.warning("Pipeline persona error: %s; keeping draft", exc)
        meta["failed_stage"] = meta["failed_stage"] or "persona"
        final = draft

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    res_chunks = chunks(format_reply(final, pages))
    return (res_chunks, meta) if include_metadata else res_chunks
