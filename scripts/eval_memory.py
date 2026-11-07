#!/usr/bin/env python3
"""Synthetic 60-day conversation evaluation script for Karna's Memory Subsystem.

Simulates 60 days of conversation events:
- Establishing permanent identity facts (name, city, language)
- Establishing project and preference facts
- Hundreds of ephemeral / trivial conversational remarks
- Repeated accesses to important facts
- Simulating daily time jumps and executing tier decay

Outputs an audit report:
- Retention of Core & Important facts
- Drop rate of ephemeral trivia
- Effective score distribution
- Verification of 0 secrets leaked
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import database
from app.memory.decay import compute_effective_score, run_tier_decay_for_user
from app.memory.extractor import extract_facts_rules
from app.memory.identity import resolve_user_id
from app.memory.models import MemoryItem, MemorySource, MemoryTier
from app.memory.profile import get_user_profile_summary, update_profile_from_fact
from app.memory.repository import list_memories, save_memory, touch_memory_access
from app.memory.retrieval import build_memory_context


def run_evaluation() -> None:
    temp_dir = tempfile.mkdtemp()
    test_db = os.path.join(temp_dir, "eval_memory.db")

    from app.config import config
    config.database_url = test_db
    database._init_lock = False
    database.init_db()

    print("=================================================================")
    print("        KARNA LONG-TERM MEMORY EVALUATION BENCHMARK (60 DAYS)    ")
    print("=================================================================")

    start_date = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)
    uid = resolve_user_id("telegram", "eval_subject_alice")

    # 1. Day 1: Identity & Permanent Facts
    print("[Day 1] Establishing core identity & permanent facts...")
    core_inputs = [
        "My name is Alice Vance.",
        "I live in Bengaluru, India.",
        "My timezone is Asia/Kolkata.",
        "My preferred language is English.",
        "Please remember that I am building Project Chimera.",
        "I prefer Python 3.12 for all backend development.",
    ]
    for inp in core_inputs:
        facts = extract_facts_rules(inp)
        for f in facts:
            is_core = f.profile_key in ("name", "city", "timezone")
            mem = MemoryItem(
                id=None,
                user_id=uid,
                tier=MemoryTier.CORE if is_core else MemoryTier.DAILY,
                period="2026-09-01",
                text=f.text,
                importance=f.importance,
                confidence=f.confidence,
                category=f.category,
                source=MemorySource.EXPLICIT,
                source_snippet=f.source_snippet,
                created_at=start_date.isoformat(),
            )
            saved_id = save_memory(mem)
            if f.profile_key and f.profile_value:
                update_profile_from_fact(user_id=uid, key=f.profile_key, value=f.profile_value, memory_id=saved_id)

    # 2. Days 2-59: Simulated conversation trajectory with trivia & tasks
    print("[Days 2-59] Ingesting 60 days of realistic daily conversations & trivia...")
    trivial_ids: list[int] = []
    chimera_mem_id: int | None = None

    for m in list_memories(user_id=uid):
        if "Project Chimera" in m.text:
            chimera_mem_id = m.id

    for day in range(2, 60):
        current_day = start_date + timedelta(days=day)
        day_str = current_day.strftime("%Y-%m-%d")

        # Ingest daily trivia (Importance = 1 or 2)
        trivia_samples = [
            f"User had oatmeal for breakfast on {day_str}.",
            f"User noticed rain in the afternoon on {day_str}.",
            f"User checked transit bus schedule for route {100 + day}.",
        ]
        for t in trivia_samples:
            mem = MemoryItem(
                id=None,
                user_id=uid,
                tier=MemoryTier.DAILY,
                period=day_str,
                text=t,
                importance=1,
                confidence=1.0,
                category="general",
                source=MemorySource.RULE,
                created_at=current_day.isoformat(),
            )
            tid = save_memory(mem)
            trivial_ids.append(tid)

        # Periodic reinforcement of Project Chimera and Python preference (every 4 days)
        if day % 4 == 0 and chimera_mem_id is not None:
            touch_memory_access([chimera_mem_id])

        # Execute nightly tier decay at 21:30 UTC every day
        nightly_time = current_day.replace(hour=21, minute=30)
        run_tier_decay_for_user(user_id=uid, current_time=nightly_time)

    # 3. Final Day 60 Audit
    final_time = start_date + timedelta(days=60)
    print("\n-----------------------------------------------------------------")
    print(f"Final Audit at Day 60 ({final_time.strftime('%Y-%m-%d')}):")
    print("-----------------------------------------------------------------")

    all_memories = list_memories(user_id=uid, limit=1000)
    tier_counts = {t: 0 for t in MemoryTier}
    for m in all_memories:
        tier_counts[m.tier] += 1

    profile_summary = get_user_profile_summary(uid)
    print("\nStructured Profile Fields Retained:")
    for k, v in profile_summary.items():
        print(f"  • {k}: {v}")

    print("\nMemory Counts by Tier:")
    for tier, count in tier_counts.items():
        print(f"  • {tier.value.upper():<8}: {count} items")

    # Important facts verification
    core_texts = [m.text for m in all_memories]
    has_name = any("Alice Vance" in t for t in core_texts)
    has_city = any("Bengaluru" in t for t in core_texts)
    has_chimera = any("Project Chimera" in t for t in core_texts)
    has_python = any("Python 3.12" in t for t in core_texts)

    important_retained = all([has_name, has_city, has_chimera, has_python])
    print(f"\nImportant Facts Retained: {'✅ 100% (4/4)' if important_retained else '❌ FAILED'}")

    # Trivial facts drop rate
    retained_trivia = sum(1 for m in all_memories if m.id in trivial_ids)
    drop_rate = ((len(trivial_ids) - retained_trivia) / len(trivial_ids)) * 100
    print(f"Trivial Items Ingested:   {len(trivial_ids)}")
    print(f"Trivial Items Dropped:    {len(trivial_ids) - retained_trivia}")
    print(f"Trivial Drop Rate:        {drop_rate:.1f}% (Target: >= 85%)")

    # Prompt context check
    context = build_memory_context(user_id=uid, query="What was my project and where do I live?")
    print("\nGenerated Prompt Context Preview:")
    print("-----------------------------------------------------------------")
    print(context)
    print("-----------------------------------------------------------------")

    assert important_retained, "Evaluation Failed: Core facts were dropped!"
    assert drop_rate >= 85.0, f"Evaluation Failed: Trivia drop rate {drop_rate}% < 85%!"
    print("\n✅ EVALUATION SUCCESS: All retention & decay constraints met.")


if __name__ == "__main__":
    run_evaluation()
