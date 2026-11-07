#!/usr/bin/env python3
"""Verify the local llama.cpp LLM endpoint before use.

Stage 2 requirement: confirm the local inference endpoint is reachable and
inspect the available model identifier via the /models endpoint.

Rules:
- Do NOT hardcode a model name.
- Do NOT fall back to any cloud LLM.
- Only the verified actual endpoint is used.
- Prints no secrets.

Usage (from project root, venv activated):
    python scripts/verify_llama.py
"""

from pathlib import Path
import sys
from typing import Optional

import httpx

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import project settings so LLM_BASE_URL comes from .env (never hardcoded).
try:
    from config.settings import settings  # type: ignore
except Exception as exc:  # pragma: no cover - environment import guard
    print(f"FAIL: could not import config.settings: {exc}", file=sys.stderr)
    sys.exit(2)


def discover_model(base_url: str, client: httpx.Client) -> Optional[str]:
    """Query GET {base_url}/models and return the first model id, or None."""
    url = base_url.rstrip("/") + "/models"
    try:
        resp = client.get(url, timeout=10.0)
    except httpx.RequestError as exc:
        print(f"FAIL: cannot reach LLM endpoint {url}: {exc}", file=sys.stderr)
        return None

    if resp.status_code != 200:
        print(
            f"FAIL: GET {url} returned HTTP {resp.status_code}",
            file=sys.stderr,
        )
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        print(f"FAIL: GET {url} did not return valid JSON: {exc}", file=sys.stderr)
        return None

    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list) or not models:
        print(f"FAIL: GET {url} returned no models: {data!r}", file=sys.stderr)
        return None

    first = models[0]
    if isinstance(first, dict):
        return first.get("id")
    return str(first)


def main() -> int:
    base_url = settings.llm_base_url.strip() if settings.llm_base_url else ""
    if not base_url:
        print(
            "FAIL: LLM_BASE_URL is not set in .env / environment. "
            "Set it to the verified llama.cpp endpoint (e.g. http://127.0.0.1:8001/v1).",
            file=sys.stderr,
        )
        return 1

    print(f"INFO: Verifying LLM endpoint: {base_url}")

    timeout = httpx.Timeout(
        connect=5.0,
        read=settings.request_timeout_seconds,
        write=5.0,
        pool=5.0,
    )
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        model_id = discover_model(base_url, client)

    if not model_id:
        print(
            "FAIL: no model identifier discovered from the LLM /models endpoint. "
            "Ensure the llama.cpp server is running and reachable.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: LLM endpoint reachable.")
    print(f"OK: discovered model identifier: {model_id}")
    print(
        "INFO: No cloud LLM fallback is used. Only the verified local endpoint is trusted."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())