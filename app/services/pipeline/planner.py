"""Phase 1: Task and search query planner with constrained JSON output."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from app.services.llm_roles import call
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.planner")

SCHEMA = {
    "type": "object",
    "properties": {
        "needs_search": {"type": "boolean"},
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "intent": {
            "type": "string",
            "enum": ["chat", "reminder", "factual", "recommendation"],
        },
        "context": {"type": "string"},
    },
    "required": ["needs_search", "queries", "intent", "context"],
    "additionalProperties": False,
}

SYSTEM = """You route messages for an assistant. Output JSON only.
- needs_search: true only if the answer needs current or external facts.
  Greetings, opinions, reminders, and simple chat are false.
- queries: 1-3 short, different web search queries (empty if no search).
- intent: the best-fitting category ("chat", "reminder", "factual", "recommendation").
- context: one sentence of conversation context the answerer needs
  (resolve words like "it" or "that" using the recent messages)."""


async def plan(user_msg: str, history: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Analyze the user message and determine if search queries are needed."""
    recent = "\n".join(f"{r}: {t}" for r, t in history[-4:])
    content = f"Recent Conversation:\n{recent}\n\nMessage: {user_msg}" if recent else f"Message: {user_msg}"

    try:
        result = await call(
            "planner",
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
            schema=SCHEMA,
            name="plan",
        )
        if isinstance(result, dict):
            return {
                "needs_search": bool(result.get("needs_search", False)),
                "queries": [str(q).strip() for q in result.get("queries", []) if str(q).strip()],
                "intent": str(result.get("intent", "chat")),
                "context": str(result.get("context", "")),
            }
    except Exception as exc:
        logger.warning("Pipeline planner failed, using fallback: %s", exc)

    return {
        "needs_search": True,
        "queries": [user_msg],
        "intent": "factual",
        "context": "",
    }
