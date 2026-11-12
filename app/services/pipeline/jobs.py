import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from . import persona, planner
from .orchestrator import answer

log = logging.getLogger("app.pipeline.jobs")
HEAVY = asyncio.Semaphore(1)          # one heavy pipeline at a time on this CPU
JOBS: Dict[Union[int, str], List["Job"]] = {}  # chat_id -> jobs, running or queued

STATUS_RE = re.compile(r"\b(done|status|update|still|how long|ready|found|any luck|progress)\b", re.I)
CANCEL_RE = re.compile(r"\b(cancel|stop|forget it|never ?mind)\b", re.I)

STAGE_TEXT = {
    "queued": "waiting behind another request",
    "starting": "just getting started",
    "planning": "working out what to search",
    "searching": "searching",
    "reading": "reading the pages",
    "filtering": "pulling out the relevant parts",
    "writing": "writing the answer",
    "polishing": "polishing the answer",
}

# Varied lines in Karna's voice. A fixed pool costs no model time.
ACKS = [
    "On it. This takes a few minutes, so go do something useful.",
    "Looking into it. Don't wait up.",
    "Working on that now. Give it a minute.",
    "Digging through the web for this. Sit tight.",
    "Processing. You'll get the answer when it's done.",
    "On the job. Don't stare at the screen.",
    "Looking up the sources now. Give me a moment.",
    "Researching. Try not to spam the chat.",
    "Running the search. Go grab some water.",
    "In progress. It'll arrive when it's ready.",
    "Underway. It takes a little patience.",
    "Started research. I'll drop the results here shortly.",
]


@dataclass
class Job:
    chat_id: Union[int, str]
    question: str
    stage: str = "queued"
    started: float = field(default_factory=time.time)
    done: bool = False
    task: Optional[asyncio.Task] = None
    meta: Optional[Dict[str, Any]] = None
    chunks: List[str] = field(default_factory=list)
    plan_data: Optional[Dict[str, Any]] = None


def active(chat_id: Union[int, str]) -> Optional[Job]:
    return next((j for j in JOBS.get(chat_id, []) if not j.done), None)


async def _typing_loop(job: Job, typing: Callable[[], Any]):
    while not job.done:
        try:
            await typing()
        except Exception:
            pass
        await asyncio.sleep(4)


async def _run(
    job: Job,
    send: Callable[[str], Any],
    typing: Callable[[], Any],
    history: List[Tuple[str, str]],
    facts: List[str],
    on_complete: Optional[Callable[[], Any]] = None,
):
    ticker = asyncio.create_task(_typing_loop(job, typing))
    try:
        async with HEAVY:
            job.stage = "starting"
            res = await answer(
                job.question,
                history,
                facts,
                progress=lambda s: setattr(job, "stage", s),
                include_metadata=True,
                plan_data=job.plan_data,
            )
            if isinstance(res, tuple):
                parts, meta = res
                job.meta = meta
                job.chunks = parts
            else:
                parts = res
                job.chunks = parts
        for p in parts:
            await send(p)
        if on_complete:
            try:
                ret = on_complete()
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                log.exception("on_complete callback failed")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("job failed for chat_id=%s", job.chat_id)
        await send("That fell over. Ask me again later.")
    finally:
        job.done = True
        ticker.cancel()
        if job.chat_id in JOBS and job in JOBS[job.chat_id]:
            JOBS[job.chat_id].remove(job)


async def _status_line(job: Job) -> str:
    mins = int((time.time() - job.started) // 60)
    facts = f"Still working. Currently: {STAGE_TEXT.get(job.stage, job.stage)}. Running for about {mins} min."
    try:
        return await persona.rewrite_status(facts)       # 2B call via "persona_fast"
    except Exception:
        return facts


async def on_message(
    chat_id: Union[int, str],
    text: str,
    history: List[Tuple[str, str]],
    facts: List[str],
    send: Callable[[str], Any],
    typing: Callable[[], Any],
    force_search: bool = False,
    initial_queries: Optional[List[str]] = None,
    on_complete: Optional[Callable[[], Any]] = None,
) -> Any:
    """Called by the Telegram handler. Returns quickly; never awaits a heavy job."""
    job = active(chat_id)
    if job and CANCEL_RE.search(text):
        if job.task and not job.task.done():
            job.task.cancel()
        return await send("Dropped it.")

    if job and len(text) < 60 and STATUS_RE.search(text):
        status_msg = await _status_line(job)
        return await send(status_msg)

    await typing()
    plan = await planner.plan(text, history)              # runs on the Fast 2B/4B
    if force_search:
        plan["needs_search"] = True
        if initial_queries and not plan.get("queries"):
            plan["queries"] = initial_queries
        elif not plan.get("queries"):
            plan["queries"] = [text]

    if not plan.get("needs_search"):
        # while a job runs, chat uses the fast model so the 9B stays free
        reply = await persona.reply_direct(text, history, facts, lane="fast" if job else "smart")
        mid = await send(reply)
        if on_complete:
            try:
                ret = on_complete()
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                pass
        return mid

    new = Job(chat_id, text, plan_data=plan)
    JOBS.setdefault(chat_id, []).append(new)
    new.task = asyncio.create_task(_run(new, send, typing, history, facts, on_complete=on_complete))
    ack_msg = random.choice(ACKS) if not job else "Queued. I'll get to it after the first one."
    return await send(ack_msg)
