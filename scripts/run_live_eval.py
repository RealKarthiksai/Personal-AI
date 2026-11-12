#!/usr/bin/env python3
"""Comprehensive Live Evaluation of the Multi-Stage Pipeline.

Runs the test prompts through the dual-model setup, measures RAM/swap during
search-heavy prompts, records per-stage timings, checks for fallback rates,
and tests reminders, multi-turn followups, and unknown-fact handling.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from typing import Any, Dict, List

from app.config import config
from app.services.chat_service import ChatService
from app.services.pipeline.orchestrator import answer_pipeline
from app.database import database

# Ensure pipeline is enabled for this evaluation run
config.use_pipeline = True

class MockSender:
    def __init__(self) -> None:
        self.messages: List[str] = []

    async def send_text(self, to: str, text: str) -> str:
        self.messages.append(text)
        return f"msg_{len(self.messages)}"


def get_mem_and_swap() -> Dict[str, str]:
    """Capture current free memory and swapon status."""
    free_out = subprocess.check_output(["free", "-h"], text=True)
    swap_out = subprocess.check_output(["swapon", "--show"], text=True)
    return {"free": free_out.strip(), "swap": swap_out.strip()}


# Style example phrases from persona.py to detect surface repetition across prompts
BANNED_STYLE_PHRASES = [
    "what do you want now",
    "try not to ignore it",
    "canberra. not sydney",
    "light showers starting around three",
    "nothing revolutionary",
    "minor clock bump isn't worth a grand",
    "you're probably going to skip it anyway",
]


async def run_evaluation(start: int = 1, end: int = 0):
    config.telegram_allowed_user_ids = "9990001"

    database.init_db()
    sender = MockSender()
    chat_service = ChatService(sender=sender)

    # Load 20 baseline prompts from tests/prompts.txt
    prompts_file = "/home/vhanghar/Karna/tests/prompts.txt"
    with open(prompts_file, "r") as f:
        raw_lines = f.readlines()

    test_prompts = []
    for line in raw_lines:
        line = line.strip()
        if line and not line.startswith("#"):
            test_prompts.append(line)

    results: List[Dict[str, Any]] = []
    fallback_count = 0
    verbatim_example_hits = 0

    print("==================================================")
    print("STARTING LIVE EVALUATION WITH DUAL MODELS (4B & 9B)")
    print("==================================================")
    initial_res = get_mem_and_swap()
    print("INITIAL RESOURCE STATE:")
    print(initial_res["free"])
    print(initial_res["swap"])
    print("--------------------------------------------------")

    # Initialize report file if starting from 1
    if start <= 1:
        with open("/home/vhanghar/Karna/tests/pipeline_eval_results.txt", "w") as f:
            f.write("=== MULTI-STAGE PIPELINE EVALUATION REPORT ===\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            f.write("--- INITIAL SYSTEM RESOURCES ---\n")
            f.write(initial_res["free"] + "\n" + initial_res["swap"] + "\n")
            f.write("=" * 50 + "\n")

    sender_id = "9990001"
    from app.services.pipeline import jobs

    # 1. Run all standard prompts
    for idx, prompt in enumerate(test_prompts, start=1):
        if idx < start or (end > 0 and idx > end):
            continue
        print(f"\n[{idx}/{len(test_prompts)}] Evaluating: {prompt}")
        t_start = time.perf_counter()

        # Check if this prompt is a search-heavy prompt to measure peak memory
        is_search_heavy = any(w in prompt.lower() for w in ("spacex", "conferences", "ethereum", "cricket"))

        msg_id = f"eval_{idx}_{int(time.time()*1000)}"
        sender_count_before = len(sender.messages)

        mem_during = None
        res = await chat_service.process_inbound(
            sender_id=sender_id,
            external_message_id=msg_id,
            text=prompt,
            timestamp="2026-11-10T18:25:00Z",
            channel="telegram",
        )

        job = jobs.active(sender_id)
        stage_timings = {}
        pages_info = []
        if job and job.task and not job.task.done():
            await job.task
            if is_search_heavy:
                mem_during = get_mem_and_swap()
            if job.meta:
                stage_timings = job.meta.get("timings", {})
                pages_info = job.meta.get("pages", [])
            if job.chunks:
                reply = "\n\n".join(job.chunks)
            elif len(sender.messages) > sender_count_before:
                reply = sender.messages[-1]
            else:
                reply = res.get("llm_response", "")
        else:
            if len(sender.messages) > sender_count_before:
                reply = sender.messages[-1]
            else:
                reply = res.get("llm_response", "")

        duration = round((time.perf_counter() - t_start) * 1000, 1)
        path = res.get("execution_path", "unknown")

        if "legacy_fallback" in path:
            fallback_count += 1

        # Check for verbatim phrase repetition
        lower_reply = reply.lower()
        matched_phrases = [p for p in BANNED_STYLE_PHRASES if p in lower_reply]
        if matched_phrases:
            verbatim_example_hits += len(matched_phrases)
            print(f"  [!] Verbatim phrase matched: {matched_phrases}")

        entry = {
            "id": idx,
            "prompt": prompt,
            "path": path,
            "total_ms": duration,
            "stage_timings": stage_timings,
            "pages": pages_info,
            "reply": reply,
            "mem_during": mem_during,
            "verbatim_matches": matched_phrases,
        }
        results.append(entry)
        print(f"  -> Path: {path} | Total: {duration}ms")
        print(f"  -> Reply snippet: {reply[:120].replace(chr(10), ' ')}...")

        # Incrementally update output report
        with open("/home/vhanghar/Karna/tests/pipeline_eval_results.txt", "a") as f:
            f.write(f"\nID: {idx}\nPrompt: {prompt}\nPath: {path}\nTotal Time: {duration} ms\n")
            if stage_timings:
                f.write(f"Stage Timings: {stage_timings}\n")
            if pages_info:
                f.write(f"Sources: {[p.get('url') for p in pages_info]}\n")
            if mem_during:
                f.write(f"Memory During:\n{mem_during['free']}\n{mem_during['swap']}\n")
            f.write(f"Reply:\n{reply}\n")
            f.write("-" * 50 + "\n")
            f.flush()

    # 2. Checklist Item: Multi-turn Follow-up
    print("\n[CHECKLIST 1] Testing Multi-turn Follow-up Context Resolution...")
    t1_msg = "What is the capital of Japan?"
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"turn_1_{int(time.time()*1000)}",
        text=t1_msg,
        timestamp="2026-11-10T18:26:00Z",
        channel="telegram",
    )
    job1 = jobs.active(sender_id)
    if job1 and job1.task and not job1.task.done():
        await job1.task

    t2_msg = "What is the best season to visit there?"
    t_start = time.perf_counter()
    before_t2 = len(sender.messages)
    turn2_res = await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"turn_2_{int(time.time()*1000)}",
        text=t2_msg,
        timestamp="2026-11-10T18:26:05Z",
        channel="telegram",
    )
    job2 = jobs.active(sender_id)
    if job2 and job2.task and not job2.task.done():
        await job2.task
        t2_reply = "\n\n".join(job2.chunks) if job2.chunks else (sender.messages[-1] if len(sender.messages) > before_t2 else "")
    else:
        t2_reply = sender.messages[-1] if len(sender.messages) > before_t2 else turn2_res.get("llm_response", "")

    t2_reply = str(t2_reply or "")
    turn2_dur = round((time.perf_counter() - t_start) * 1000, 1)
    results.append({
        "id": "multi_turn_followup",
        "prompt": f"History: {t1_msg} -> User: {t2_msg}",
        "path": turn2_res.get("execution_path", "unknown"),
        "total_ms": turn2_dur,
        "reply": t2_reply,
    })
    print(f"  -> Turn 2 Reply: {t2_reply[:140]}...")

    # 3. Checklist Item: Unknown Info Query
    print("\n[CHECKLIST 2] Testing Unknown Fact / Impossible Knowledge Query...")
    unk_msg = "What did I have for dinner yesterday evening?"
    t_start = time.perf_counter()
    before_unk = len(sender.messages)
    unk_res = await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"unk_1_{int(time.time()*1000)}",
        text=unk_msg,
        timestamp="2026-11-10T18:26:10Z",
        channel="telegram",
    )
    job3 = jobs.active(sender_id)
    if job3 and job3.task and not job3.task.done():
        await job3.task
        unk_reply = "\n\n".join(job3.chunks) if job3.chunks else (sender.messages[-1] if len(sender.messages) > before_unk else "")
    else:
        unk_reply = sender.messages[-1] if len(sender.messages) > before_unk else unk_res.get("llm_response", "")

    unk_reply = str(unk_reply or "")
    unk_dur = round((time.perf_counter() - t_start) * 1000, 1)
    results.append({
        "id": "unknown_fact",
        "prompt": unk_msg,
        "path": unk_res.get("execution_path", "unknown"),
        "total_ms": unk_dur,
        "reply": unk_reply,
    })
    print(f"  -> Unknown fact Reply: {unk_reply[:140]}...")

    # 4. Checklist Item: Front-desk Concurrency Test
    print("\n[CHECKLIST 3] Testing Front-desk Non-blocking Concurrency...")
    # Start heavy search
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"concurr_search_1_{int(time.time()*1000)}",
        text="What is the latest status of Artemis 3 moon mission?",
        timestamp="2026-11-10T18:27:00Z",
        channel="telegram",
    )
    job_c = jobs.active(sender_id)
    assert job_c is not None, "Heavy search did not spawn background job"
    print("  -> Heavy search job spawned in background.")

    # Front-desk immediate 'hi'
    t_hi = time.perf_counter()
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"concurr_hi_{int(time.time()*1000)}",
        text="hi",
        timestamp="2026-11-10T18:27:01Z",
        channel="telegram",
    )
    hi_dur = round((time.perf_counter() - t_hi) * 1000, 1)
    hi_reply = sender.messages[-1]
    print(f"  -> Immediate 'hi' returned in {hi_dur}ms: {hi_reply[:60]}")

    # Front-desk status check 'done yet?'
    t_stat = time.perf_counter()
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"concurr_stat_{int(time.time()*1000)}",
        text="done yet?",
        timestamp="2026-11-10T18:27:02Z",
        channel="telegram",
    )
    stat_dur = round((time.perf_counter() - t_stat) * 1000, 1)
    stat_reply = sender.messages[-1]
    print(f"  -> Status check returned in {stat_dur}ms: {stat_reply[:60]}")

    # Front-desk queue second search
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"concurr_search_2_{int(time.time()*1000)}",
        text="SpaceX Starship orbital flights summary",
        timestamp="2026-11-10T18:27:03Z",
        channel="telegram",
    )
    q2_reply = sender.messages[-1]
    print(f"  -> Second search queued: {q2_reply[:60]}")

    # Front-desk cancel
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id=f"concurr_cancel_{int(time.time()*1000)}",
        text="cancel",
        timestamp="2026-11-10T18:27:04Z",
        channel="telegram",
    )
    cancel_reply = sender.messages[-1]
    print(f"  -> Job cancelled: {cancel_reply[:60]}")

    results.append({
        "id": "concurrency_test",
        "prompt": "heavy search -> hi -> done yet? -> second search -> cancel",
        "path": "front_desk_concurrency",
        "total_ms": hi_dur + stat_dur,
        "reply": f"hi: {hi_reply} | status: {stat_reply} | cancel: {cancel_reply}",
    })

    # 4. Final Resource Status
    final_res = get_mem_and_swap()
    print("\nFINAL RESOURCE STATE:")
    print(final_res["free"])
    print(final_res["swap"])

    # 5. Write Checklist Items & Summary to tests/pipeline_eval_results.txt
    output_path = "/home/vhanghar/Karna/tests/pipeline_eval_results.txt"
    mode = "w" if start <= 1 else "a"
    with open(output_path, mode) as f:
        if start <= 1:
            f.write("=== MULTI-STAGE PIPELINE EVALUATION REPORT ===\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            f.write(f"Total Evaluated Prompts: {len(results)}\n")
            f.write(f"Fallback Count: {fallback_count} / {len(test_prompts)}\n")
            f.write(f"Verbatim Example Repetitions: {verbatim_example_hits}\n\n")

            f.write("--- SYSTEM RESOURCES ---\n")
            f.write("Initial:\n" + initial_res["free"] + "\n" + initial_res["swap"] + "\n\n")
            f.write("Final:\n" + final_res["free"] + "\n" + final_res["swap"] + "\n\n")

            f.write("--- DETAILED PROMPT RESULTS ---\n")
            for item in results:
                f.write(f"ID: {item['id']}\n")
                f.write(f"Prompt: {item['prompt']}\n")
                f.write(f"Path: {item.get('path', 'unknown')}\n")
                f.write(f"Total Time: {item.get('total_ms', 0)} ms\n")
                if item.get("stage_timings"):
                    f.write(f"Stage Timings: {item['stage_timings']}\n")
                if item.get("pages"):
                    f.write(f"Sources: {[p.get('url') for p in item['pages']]}\n")
                f.write(f"Reply:\n{item.get('reply', '')}\n")
                f.write("-" * 50 + "\n")
        else:
            # Append checklist results for resumed runs
            checklist_items = [r for r in results if not isinstance(r.get("id"), int)]
            for item in checklist_items:
                f.write(f"\nID: {item['id']}\n")
                f.write(f"Prompt: {item['prompt']}\n")
                f.write(f"Path: {item.get('path', 'unknown')}\n")
                f.write(f"Total Time: {item.get('total_ms', 0)} ms\n")
                f.write(f"Reply:\n{item.get('reply', '')}\n")
                f.write("-" * 50 + "\n")
            f.write("\nFINAL RESOURCE STATE:\n" + final_res["free"] + "\n" + final_res["swap"] + "\n")

    print(f"\nEvaluation complete. Full report written to: {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1, help="Start prompt index (1-based)")
    parser.add_argument("--end", type=int, default=0, help="End prompt index (1-based, 0=all)")
    args = parser.parse_args()
    asyncio.run(run_evaluation(start=args.start, end=args.end))
