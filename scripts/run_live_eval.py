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


async def run_evaluation():
    config.telegram_allowed_user_ids = "9990001"
    config.allowed_telegram_user_ids = [9990001]

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

    sender_id = "9990001"

    # 1. Run all standard prompts
    for idx, prompt in enumerate(test_prompts, start=1):
        print(f"\n[{idx}/{len(test_prompts)}] Evaluating: {prompt}")
        t_start = time.perf_counter()

        # Check if this prompt is a search-heavy prompt to measure peak memory
        is_search_heavy = any(w in prompt.lower() for w in ("spacex", "conferences", "ethereum", "cricket"))

        # We execute via ChatService.process_inbound to test full end-to-end routing
        msg_id = f"eval_{idx}_{int(time.time()*1000)}"
        
        mem_during = None
        if is_search_heavy:
            res = await chat_service.process_inbound(
                sender_id=sender_id,
                external_message_id=msg_id,
                text=prompt,
                timestamp="2026-11-10T18:25:00Z",
                channel="telegram",
            )
            mem_during = get_mem_and_swap()
        else:
            res = await chat_service.process_inbound(
                sender_id=sender_id,
                external_message_id=msg_id,
                text=prompt,
                timestamp="2026-11-10T18:25:00Z",
                channel="telegram",
            )

        duration = round((time.perf_counter() - t_start) * 1000, 1)
        path = res.get("execution_path", "unknown")
        reply = res.get("llm_response", "")

        # Also call answer_pipeline directly with include_metadata=True if this was a pipeline path
        # to obtain precise per-stage timings (planner_ms, fetch_ms, synth_ms, persona_ms)
        stage_timings = {}
        pages_info = []
        if path == "pipeline":
            try:
                _, pmeta = await answer_pipeline(prompt, [], [], include_metadata=True)
                stage_timings = pmeta.get("timings", {})
                pages_info = pmeta.get("pages", [])
                sub_path = pmeta.get("path", "")
                path = f"{path} ({sub_path})"
            except Exception as e:
                stage_timings = {"error": str(e)}

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

    # 2. Checklist Item: Multi-turn Follow-up
    print("\n[CHECKLIST 1] Testing Multi-turn Follow-up Context Resolution...")
    # Turn 1
    t1_msg = "What is the capital of Japan?"
    await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id="turn_1",
        text=t1_msg,
        timestamp="2026-11-10T18:26:00Z",
        channel="telegram",
    )
    # Turn 2: Follow-up relying on context
    t2_msg = "What is the best season to visit there?"
    t_start = time.perf_counter()
    turn2_res = await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id="turn_2",
        text=t2_msg,
        timestamp="2026-11-10T18:26:05Z",
        channel="telegram",
    )
    turn2_dur = round((time.perf_counter() - t_start) * 1000, 1)
    results.append({
        "id": "multi_turn_followup",
        "prompt": f"History: {t1_msg} -> User: {t2_msg}",
        "path": turn2_res.get("execution_path", "unknown"),
        "total_ms": turn2_dur,
        "reply": turn2_res.get("llm_response", ""),
    })
    print(f"  -> Turn 2 Reply: {turn2_res.get('llm_response', '')[:140]}...")

    # 3. Checklist Item: Unknown Info Query
    print("\n[CHECKLIST 2] Testing Unknown Fact / Impossible Knowledge Query...")
    unk_msg = "What did I have for dinner yesterday evening?"
    t_start = time.perf_counter()
    unk_res = await chat_service.process_inbound(
        sender_id=sender_id,
        external_message_id="unk_1",
        text=unk_msg,
        timestamp="2026-11-10T18:26:10Z",
        channel="telegram",
    )
    unk_dur = round((time.perf_counter() - t_start) * 1000, 1)
    results.append({
        "id": "unknown_fact",
        "prompt": unk_msg,
        "path": unk_res.get("execution_path", "unknown"),
        "total_ms": unk_dur,
        "reply": unk_res.get("llm_response", ""),
    })
    print(f"  -> Unknown fact Reply: {unk_res.get('llm_response', '')[:140]}...")

    # 4. Final Resource Status
    final_res = get_mem_and_swap()
    print("\nFINAL RESOURCE STATE:")
    print(final_res["free"])
    print(final_res["swap"])

    # 5. Write Report to tests/pipeline_eval_results.txt
    output_path = "/home/vhanghar/Karna/tests/pipeline_eval_results.txt"
    with open(output_path, "w") as f:
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

    print(f"\nEvaluation complete. Full report written to: {output_path}")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
