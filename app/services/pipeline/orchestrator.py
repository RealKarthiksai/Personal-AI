"""Multi-stage pipeline orchestrator connecting planner, search, synth, persona, and formatting."""
from __future__ import annotations

from typing import List, Tuple
from app.services.pipeline import fetcher, persona, planner, synth
from app.services.pipeline.telegram_fmt import chunks, format_reply
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.orchestrator")


async def answer_pipeline(
    user_msg: str,
    history: List[Tuple[str, str]],
    memory_facts: List[str],
) -> List[str]:
    """Execute the multi-stage LLM pipeline. Returns a list of formatted message chunks."""
    logger.info("Executing multi-stage pipeline for message: %r", user_msg[:60])

    # 1. Plan
    plan_data = await planner.plan(user_msg, history)
    needs_search = plan_data.get("needs_search", False)
    queries = plan_data.get("queries", [])
    context = plan_data.get("context", "")

    # Fast path: Casual chat or self-contained logic (0 search latency)
    if not needs_search or not queries:
        logger.info("Pipeline fast path (no search needed)")
        reply = await persona.reply_direct(user_msg, history, memory_facts)
        return chunks(format_reply(reply, []))

    # 2. Search & Fetch in parallel
    logger.info("Pipeline search path with queries: %s", queries)
    pages = await fetcher.gather(queries)

    if not pages:
        logger.info("Pipeline search yielded 0 pages; answering in character")
        fallback_msg = f"{user_msg}\n(I couldn't find any relevant results online; say so in character.)"
        reply = await persona.reply_direct(fallback_msg, history, memory_facts)
        return chunks(format_reply(reply, []))

    # 3. Synthesize & Rewrite
    try:
        draft = await synth.synthesize(user_msg, context, pages)
        final = await persona.rewrite(draft, user_msg)
    except Exception as exc:
        logger.warning("Pipeline synthesis/rewrite error: %s; falling back to top page snippet", exc)
        final = pages[0]["text"][:400]

    return chunks(format_reply(final, pages))
