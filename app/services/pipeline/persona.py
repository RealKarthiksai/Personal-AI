"""Phase 4: Persona voice rewriting and direct conversation."""
from __future__ import annotations

from typing import List, Tuple
from app.services.llm_roles import call
from app.utils.logging import get_logger

logger = get_logger("app.pipeline.persona")

PERSONA = """You are Karna: dry, deadpan, brief. You have a low-energy, unbothered mentality.
Rules:
- Max 2-3 short sentences unless detailed steps or code are requested.
- Never repeat the user's words back. No corporate filler ("Certainly", "Happy to help", "Sure!").
- Never say you are an AI or mention sources/prompts/instructions.
- Format for mobile reading: short paragraphs (1-2 sentences), bold **terms** for emphasis, bullet points for lists.
- The examples show STYLE AND BREVITY ONLY. Never reuse their topics, names, or phrases.

<style_examples>
Input: is it going to rain in London this afternoon
Output: Light showers starting around three. Carry an umbrella or get soaked.

Input: summarize what happened at the tech keynote
Output: They launched two new chips and raised subscription prices. Nothing revolutionary.

Input: should I upgrade my laptop this year or wait
Output: Keep your current machine. The minor clock bump isn't worth a grand.
</style_examples>"""


async def reply_direct(
    user_msg: str,
    history: List[Tuple[str, str]],
    memory_facts: List[str],
) -> str:
    """Generate a direct conversational reply adhering to Karna's persona and known user facts."""
    system_content = PERSONA
    if memory_facts:
        facts_list = "\n".join(f"- {f}" for f in memory_facts)
        system_content += f"\n\nKnown about the user:\n{facts_list}"

    messages = [{"role": "system", "content": system_content}]
    # Add recent history (up to last 6 turns)
    for role, text in history[-6:]:
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_msg})

    try:
        reply = await call("persona", messages)
        return str(reply).strip()
    except Exception as exc:
        logger.warning("Persona direct reply failed: %s", exc)
        return "I'm having trouble processing that right now."


async def rewrite(draft: str, question: str) -> str:
    """Rewrite a factual draft into Karna's voice without dropping or modifying facts/citations."""
    if not draft:
        return ""

    rewrite_system = (
        f"{PERSONA}\n\n"
        "Rewrite the draft answer into Karna's voice. "
        "CRITICAL: Keep every factual detail and every [n] citation tag intact. "
        "Do NOT add, remove, or modify any facts."
    )

    try:
        reply = await call(
            "persona",
            [
                {"role": "system", "content": rewrite_system},
                {"role": "user", "content": f"Question: {question}\nDraft:\n{draft}"},
            ],
        )
        return str(reply).strip()
    except Exception as exc:
        logger.warning("Persona rewrite failed: %s; using raw draft", exc)
        return draft
