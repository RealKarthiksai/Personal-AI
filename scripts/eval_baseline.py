"""Baseline evaluation runner for prompts.txt against running LLM server."""
import asyncio
import os
import sys
import time
import httpx

from app.services.chat_service import get_dynamic_system_prompt

PROMPTS_FILE = "tests/prompts.txt"
OUTPUT_FILE = "tests/baseline.txt"
LLM_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8001/v1")

async def run_eval():
    if not os.path.exists(PROMPTS_FILE):
        print(f"File not found: {PROMPTS_FILE}")
        sys.exit(1)

    with open(PROMPTS_FILE, "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    system_prompt = get_dynamic_system_prompt(is_research=False, has_memory=False)
    results = []

    print(f"Running baseline evaluation on {len(lines)} prompts against {LLM_URL}...")
    async with httpx.AsyncClient(timeout=90.0) as client:
        for idx, prompt in enumerate(lines, 1):
            t0 = time.monotonic()
            payload = {
                "model": "qwen3.5-2b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 250,
                "temperature": 0.7,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            try:
                resp = await client.post(f"{LLM_URL}/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content", "")
                content = content.strip()
                dt = time.monotonic() - t0
                print(f"[{idx}/{len(lines)}] ({dt:.2f}s) {prompt[:30]}... -> {content[:40]}...")
                results.append(f"=== PROMPT {idx} ===\nInput: {prompt}\nTime: {dt:.2f}s\nOutput:\n{content}\n")
            except Exception as e:
                dt = time.monotonic() - t0
                print(f"[{idx}/{len(lines)}] FAILED ({dt:.2f}s): {e}")
                results.append(f"=== PROMPT {idx} ===\nInput: {prompt}\nTime: {dt:.2f}s\nERROR: {e}\n")

    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(results))
    print(f"\nBaseline saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(run_eval())
