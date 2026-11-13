"""Multi-stage pipeline orchestrator connecting planner, search, synth, persona, and formatting."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from app.services.pipeline import fetcher, filter, persona, planner, synth
from app.services.pipeline.telegram_fmt import chunks, format_reply
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.orchestrator")


class PipelineResult(tuple):
    """Named-tuple compatible result returned by the multi-stage pipeline.

    Supports sequence unpacking `(chunks, meta) = result` for seamless
    backwards compatibility with existing tuple consumers, while providing
    strongly typed property access.
    """

    def __new__(cls, chunks: List[str], metadata: Dict[str, Any]):
        return super().__new__(cls, (chunks, metadata))

    @property
    def chunks(self) -> List[str]:
        """List of formatted message chunks ready for transmission."""
        return self[0]

    @property
    def metadata(self) -> Dict[str, Any]:
        """Pipeline telemetry and stage execution metadata."""
        return self[1]

    @property
    def text(self) -> str:
        """Full combined response text across all chunks."""
        return "".join(self.chunks)

    @property
    def path(self) -> str:
        """Pipeline routing path (e.g. 'pipeline-fast', 'pipeline-search')."""
        return str(self.metadata.get("path", "unknown"))

    @property
    def timings(self) -> Dict[str, float]:
        """Stage execution durations in milliseconds."""
        return self.metadata.get("timings", {})

    @property
    def sources(self) -> List[str]:
        """List of URLs kept in the evidence bundle."""
        pages = self.metadata.get("pages", [])
        return [p.get("url", "") for p in pages if isinstance(p, dict) and p.get("url")]


async def answer_pipeline(
    user_msg: str,
    history: List[Tuple[str, str]],
    memory_facts: List[str],
    include_metadata: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    plan_data: Optional[Dict[str, Any]] = None,
) -> Union[List[str], PipelineResult]:
    """Execute the multi-stage LLM pipeline with evidence filtering and progress reporting."""
    def _notify(stage: str):
        if progress:
            try:
                progress(stage)
            except Exception:
                pass

    logger.info("Executing multi-stage pipeline for message: %r", user_msg[:60])
    t0 = time.perf_counter()
    timings: Dict[str, float] = {
        "planner_ms": 0.0,
        "fetch_ms": 0.0,
        "filter_ms": 0.0,
        "synth_ms": 0.0,
        "persona_ms": 0.0,
        "total_ms": 0.0,
    }
    meta: Dict[str, Any] = {
        "path": "pipeline-unknown",
        "timings": timings,
        "queries": [],
        "pages_count": 0,
        "kept_count": 0,
        "failed_stage": None,
    }

    # 1. Plan
    _notify("planning")
    if plan_data is None:
        t_plan_start = time.perf_counter()
        plan_data = await planner.plan(user_msg, history)
        timings["planner_ms"] = round((time.perf_counter() - t_plan_start) * 1000, 1)
    else:
        timings["planner_ms"] = 0.0

    needs_search = plan_data.get("needs_search", False)
    queries = plan_data.get("queries", [])
    context = plan_data.get("context", "")
    meta["queries"] = queries

    # Fast path: Casual chat or self-contained logic (0 search latency)
    if not needs_search or not queries:
        logger.info("Pipeline fast path (no search needed)")
        meta["path"] = "pipeline-fast"
        _notify("writing")
        t_persona_start = time.perf_counter()
        reply = await persona.reply_direct(user_msg, history, memory_facts)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res_chunks = chunks(format_reply(reply, []))
        return PipelineResult(res_chunks, meta) if include_metadata else res_chunks

    # 2. Search & Fetch in parallel
    logger.info("Pipeline search path with queries: %s", queries)
    meta["path"] = "pipeline-search"
    _notify("searching")
    t_fetch_start = time.perf_counter()
    pages = await fetcher.gather(queries)
    timings["fetch_ms"] = round((time.perf_counter() - t_fetch_start) * 1000, 1)
    meta["pages_count"] = len(pages)

    if not pages:
        logger.info("Pipeline search yielded 0 pages; answering in character")
        meta["path"] = "pipeline-search-empty"
        _notify("writing")
        t_persona_start = time.perf_counter()
        fallback_msg = f"{user_msg}\n(I couldn't find any relevant results online; say so in character.)"
        reply = await persona.reply_direct(fallback_msg, history, memory_facts)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res_chunks = chunks(format_reply(reply, []))
        return PipelineResult(res_chunks, meta) if include_metadata else res_chunks

    # 3. Filter Evidence (Passage overlap + 2B verbatim extraction)
    _notify("reading")
    _notify("filtering")
    t_filter_start = time.perf_counter()
    kept = await filter.filter_pages(user_msg, queries, pages)
    timings["filter_ms"] = round((time.perf_counter() - t_filter_start) * 1000, 1)
    meta["kept_count"] = len(kept)
    meta["pages"] = [{"url": p.get("url", "")} for p in kept]

    if not kept:
        logger.info("Evidence filtering yielded 0 relevant excerpts; taking fallback path")
        meta["path"] = "pipeline-filtered-empty"
        _notify("writing")
        t_persona_start = time.perf_counter()
        fallback_msg = f"{user_msg}\n(I found pages online but none contained relevant facts; say so in character.)"
        reply = await persona.reply_direct(fallback_msg, history, memory_facts)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res_chunks = chunks(format_reply(reply, []))
        return PipelineResult(res_chunks, meta) if include_metadata else res_chunks

    # 4. Synthesize with 9B (on filtered evidence)
    _notify("writing")
    try:
        t_synth_start = time.perf_counter()
        draft = await synth.synthesize(user_msg, context, kept)
        timings["synth_ms"] = round((time.perf_counter() - t_synth_start) * 1000, 1)
    except Exception as exc:
        logger.warning("Pipeline synthesis error: %s; falling back to top snippet", exc)
        meta["failed_stage"] = "synth"
        draft = kept[0]["text"][:400]

    # 5. Persona Rewrite & Polish
    _notify("polishing")
    try:
        t_persona_start = time.perf_counter()
        final = await persona.rewrite(draft, user_msg)
        timings["persona_ms"] = round((time.perf_counter() - t_persona_start) * 1000, 1)
    except Exception as exc:
        logger.warning("Pipeline persona error: %s; keeping draft", exc)
        meta["failed_stage"] = meta["failed_stage"] or "persona"
        final = draft

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    res_chunks = chunks(format_reply(final, kept))
    return PipelineResult(res_chunks, meta) if include_metadata else res_chunks


# Alias for job runner and external callers
answer = answer_pipeline
