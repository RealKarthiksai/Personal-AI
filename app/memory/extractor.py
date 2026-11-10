"""Fact extraction combining deterministic rules and constrained LLM analysis with strict grounding verification."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.memory.config import get_memory_profile
from app.memory.models import ExtractedFact, FactCategory
from app.memory.redactor import is_sensitive_category, redact_sensitive_text
from app.services.llm_client import LLMClientError, LLMClient
from app.utils.logging import get_logger

logger = get_logger("app.memory.extractor")

# Deterministic patterns for rules-based extraction
RULE_PATTERNS: List[Tuple[re.Pattern, str, int, Optional[str]]] = [
    # (Regex, Category, Importance, ProfileKey or None)
    # 1. Name
    (re.compile(r"(?i)\b(?:my name is|call me|i go by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"), FactCategory.IDENTITY.value, 5, "name"),
    # 2. Location / City
    (re.compile(r"(?i)\b(?:i live in|i am based in|i'm located in|i reside in)\s+([A-Za-z\s]+?)(?:[.,;]|\band\b|$)"), FactCategory.IDENTITY.value, 4, "city"),
    # 3. Timezone
    (re.compile(r"(?i)\b(?:my timezone is|i'm in\s+(?:the\s+)?timezone)\s+([A-Za-z/_]+)"), FactCategory.IDENTITY.value, 5, "timezone"),
    # 4. Language
    (re.compile(r"(?i)\b(?:i speak|my native language is|my preferred language is)\s+([A-Za-z]+)"), FactCategory.PREFERENCE.value, 4, "language"),
    # 5. Explicit remember instructions
    (re.compile(r"(?i)\b(?:remember(?:\s+that)?|please\s+remember|keep\s+in\s+mind|note\s+that)\s*[:,\s]\s*(.+)"), FactCategory.GENERAL.value, 4, None),
    # 6. Preferences
    (re.compile(r"(?i)\b(?:i prefer|i always like|i like to|i love to|i enjoy)\s+(.+)"), FactCategory.PREFERENCE.value, 3, None),
    (re.compile(r"(?i)\b(?:don't|never|i dislike|i hate)\s+(.+)"), FactCategory.PREFERENCE.value, 3, None),
    # 7. Current Project / Work
    (re.compile(r"(?i)\b(?:i'm working on|my project is|i am building)\s+(.+)"), FactCategory.PROJECT.value, 4, "current_project"),
]

# Common English stop words to exclude from keyword grounding checks
STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "at",
    "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "all", "any", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should",
    "now", "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
    "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself",
    "she", "her", "hers", "herself", "it", "its", "itself", "they", "them",
    "their", "theirs", "themselves", "what", "which", "who", "whom", "this",
    "that", "these", "those", "am", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "having", "do", "does", "did", "doing",
    "user", "likes", "prefers", "wants", "works",
}


def verify_grounding(
    fact_text: str,
    source_text: str,
    min_overlap: float = 0.6,
) -> bool:
    """Check that fact claims are strictly supported by the source user message.

    Rules:
    1. All numbers in the fact must exist in the source text.
    2. Non-stopword tokens must achieve at least min_overlap in the source text.
    """
    clean_fact = fact_text.lower()
    clean_src = source_text.lower()

    # Rule 1: Check numbers
    fact_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", clean_fact)
    for num in fact_numbers:
        if num not in clean_src:
            logger.debug("Grounding failed: number %s missing from source", num)
            return False

    # Rule 2: Token overlap of substantive keywords
    fact_tokens = [w for w in re.findall(r"\b[a-z0-9_-]{3,}\b", clean_fact) if w not in STOP_WORDS]
    if not fact_tokens:
        # If fact has only small words, ensure full substring or phrase presence
        return clean_fact in clean_src

    matched = sum(1 for token in fact_tokens if token in clean_src)
    overlap = matched / len(fact_tokens)

    is_grounded = overlap >= min_overlap
    if not is_grounded:
        logger.debug(
            "Grounding failed: overlap %.2f < %.2f for fact: %r",
            overlap,
            min_overlap,
            fact_text,
        )
    return is_grounded


def extract_facts_rules(
    text: str,
    message_id: Optional[int] = None,
) -> List[ExtractedFact]:
    """Fast deterministic pattern-matching extraction for names, preferences, and explicit commands."""
    redacted_text = redact_sensitive_text(text)
    facts: List[ExtractedFact] = []
    snippet = redacted_text[:200]

    for pattern, category, importance, profile_key in RULE_PATTERNS:
        match = pattern.search(redacted_text)
        if match:
            captured = match.group(1).strip()
            # Clean trailing punctuation
            captured = captured.rstrip(".,;!? ")
            if len(captured) < 2:
                continue

            # Format fact text
            if profile_key == "name":
                fact_str = f"User's name is {captured}."
                prof_val = captured
            elif profile_key == "city":
                fact_str = f"User lives in {captured}."
                prof_val = captured
            elif profile_key == "timezone":
                fact_str = f"User's timezone is {captured}."
                prof_val = captured
            elif profile_key == "language":
                fact_str = f"User speaks {captured}."
                prof_val = captured
            elif profile_key == "current_project":
                fact_str = f"User is working on {captured}."
                prof_val = captured
            else:
                fact_str = f"User noted: {captured}."
                prof_val = None

            facts.append(
                ExtractedFact(
                    text=fact_str,
                    category=category,
                    importance=importance,
                    confidence=1.0,
                    source_snippet=snippet,
                    source_message_id=message_id,
                    profile_key=profile_key,
                    profile_value=prof_val,
                )
            )

    return facts


async def extract_facts_llm(
    text: str,
    llm_client: LLMClient,
    message_id: Optional[int] = None,
) -> List[ExtractedFact]:
    """Open-ended fact extraction using local LLM with constrained JSON output and grounding verification."""
    profile = get_memory_profile()
    if not profile.llm_extraction_enabled:
        return []

    redacted_text = redact_sensitive_text(text)
    snippet = redacted_text[:200]

    system_prompt = (
        "You are an offline memory extraction module for a personal assistant. "
        "Extract key personal facts, preferences, projects, or people mentioned by the user. "
        "Rules:\n"
        "1. Never invent or assume facts. Only extract what the user explicitly stated.\n"
        "2. Do not extract sensitive secrets, passwords, financial accounts, or health details.\n"
        "3. Output ONLY a valid JSON list of objects with fields:\n"
        "   - text: a concise 1-sentence statement starting with 'User...'\n"
        "   - category: 'identity' | 'preference' | 'project' | 'person' | 'work' | 'general'\n"
        "   - importance: integer 1 to 5 (1=small talk, 3=useful context, 4=plans/projects, 5=permanent identity)\n"
        "   - confidence: float between 0.5 and 1.0\n"
        "4. If no significant facts exist, return an empty list: []"
    )

    user_prompt = (
        "<user_utterance>\n"
        f"{redacted_text}\n"
        "</user_utterance>\n\n"
        "Extract personal facts from the utterance above as JSON:"
    )

    data = None
    if config.use_pipeline:
        try:
            from app.services.llm_roles import call as role_call
            FACT_SCHEMA = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["identity", "preference", "project", "person", "work", "general"],
                        },
                        "importance": {"type": "integer"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["text", "category", "importance", "confidence"],
                    "additionalProperties": False,
                },
            }
            data = await role_call(
                "extractor",
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                schema=FACT_SCHEMA,
                name="extracted_facts",
            )
        except Exception as e:
            logger.debug("Pipeline extractor role failed: %s; falling back to direct LLM call", e)
            data = None

    if data is None:
        try:
            raw_reply = await llm_client.generate(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt,
                max_tokens=300,
                temperature=0.1,
            )
        except LLMClientError as e:
            logger.warning("LLM fact extraction failed: %s", e)
            return []

        # Parse JSON reply
        try:
            clean_json = raw_reply.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```", 1)[1].split("```", 1)[0].strip()

            data = json.loads(clean_json)
            if not isinstance(data, list):
                return []
        except Exception as e:
            logger.debug("Failed to parse LLM JSON extraction: %s | raw=%r", e, raw_reply)
            return []

    valid_facts: List[ExtractedFact] = []
    min_overlap = profile.grounding_min_overlap

    for item in data:
        if not isinstance(item, dict):
            continue
        fact_text = str(item.get("text", "")).strip()
        if not fact_text:
            continue

        cat = str(item.get("category", "general")).lower()
        if is_sensitive_category(cat, is_explicit=False):
            continue

        # Strict grounding verification against original user text
        if not verify_grounding(fact_text, redacted_text, min_overlap=min_overlap):
            logger.info("Rejected ungrounded fact: %r", fact_text)
            continue

        try:
            imp = max(1, min(5, int(item.get("importance", 2))))
        except Exception:
            imp = 2

        try:
            conf = max(0.1, min(1.0, float(item.get("confidence", 0.9))))
        except Exception:
            conf = 0.9

        valid_facts.append(
            ExtractedFact(
                text=fact_text,
                category=cat,
                importance=imp,
                confidence=conf,
                source_snippet=snippet,
                source_message_id=message_id,
            )
        )

    return valid_facts


async def extract_all_facts(
    text: str,
    llm_client: Optional[LLMClient] = None,
    message_id: Optional[int] = None,
) -> List[ExtractedFact]:
    """Run rules first, followed by constrained-LLM extraction if enabled, and deduplicate."""
    facts = extract_facts_rules(text, message_id=message_id)

    # If explicit remember or specific rules fired, LLM may not be required for small messages
    if llm_client is not None and len(text.split()) > 6:
        llm_facts = await extract_facts_llm(text, llm_client, message_id=message_id)
        # Dedupe by text similarity
        existing_texts = {f.text.lower() for f in facts}
        for lf in llm_facts:
            if lf.text.lower() not in existing_texts:
                facts.append(lf)
                existing_texts.add(lf.text.lower())

    return facts
