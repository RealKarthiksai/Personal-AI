"""Multi-stage role-based LLM client supporting schema-constrained generation."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import httpx

from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.llm_roles")


def get_role_config(role: str) -> dict:
    fast_url = config.llm_fast_url
    smart_url = config.llm_smart_url

    roles: Dict[str, dict] = {
        "filter":       dict(url=fast_url,  temperature=0.0, top_p=0.9, max_tokens=400, timeout=180),
        "synth":        dict(url=smart_url, temperature=0.3, top_p=0.8, top_k=20, max_tokens=500, timeout=600),
        "persona":      dict(url=smart_url, temperature=0.7, top_p=0.8, top_k=20, presence_penalty=0.6, max_tokens=300, timeout=300),
        "persona_fast": dict(url=fast_url,  temperature=0.7, top_p=0.8, top_k=20, presence_penalty=0.6, max_tokens=200, timeout=120),
        "planner":      dict(url=fast_url,  temperature=0.1, top_p=0.9, max_tokens=300, timeout=120),
        "extractor":    dict(url=fast_url,  temperature=0.0, top_p=0.9, max_tokens=300, timeout=120),
    }
    return dict(roles.get(role, roles["persona"]))


async def call(
    role: str,
    messages: List[Dict[str, str]],
    schema: Optional[dict] = None,
    name: str = "out",
) -> Any:
    cfg = get_role_config(role)
    url = cfg.pop("url")
    timeout = float(cfg.pop("timeout", config.stage_timeout))

    body: Dict[str, Any] = {
        "messages": messages,
        **cfg,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        }

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{url}/v1/chat/completions", json=body)
        r.raise_for_status()
        res_json = r.json()
        first_choice = res_json["choices"][0]["message"]
        content = first_choice.get("content") or first_choice.get("reasoning_content", "")

    content = content.strip()
    if schema:
        raw = content
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        start = raw.find("{") if schema.get("type") == "object" else raw.find("[")
        end = raw.rfind("}") if schema.get("type") == "object" else raw.rfind("]")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]
        try:
            return json.loads(raw)
        except Exception as e:
            logger.warning("Failed to parse JSON response from role %s: %s | raw=%r", role, e, content)
            raise

    return content
