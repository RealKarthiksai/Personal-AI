"""Chat orchestration pipeline (channel-agnostic).

Incoming message
    -> Sender authorization
    -> Duplicate detection
    -> Store incoming message
    -> Retrieve recent conversation history
    -> Call local LLM
    -> Store generated response
    -> Send response through the configured channel
    -> Record delivery result

The messaging channel (e.g. Telegram) is injected as a `sender` object that
must expose `send_text(to: str, text: str) -> Optional[str]` returning the
channel message id on success, or None on failure. This keeps the pipeline
independent of any specific payload format.

All steps are async-safe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Protocol

from app.config import config
from app.context.temporal import build_system_temporal_prompt
from app.database import repository
from app.services.llm_client import LLMClient, LLMClientError
from app.services.tool_router import ToolRouter, tool_router as default_tool_router
from app.utils.logging import get_logger

logger = get_logger("app.chat_service")

DEFAULT_CONVERSATIONAL_PROMPT = (
    "You are Karna, a warm, lively, witty, and intelligent personal AI companion. "
    "Talk naturally and conversationally, like a smart, engaging friend.\n\n"
    "Conversation Rules:\n"
    "- Tone: Friendly, vibrant, warm, and natural. Speak in direct human language.\n"
    "- Formatting: NEVER use rigid corporate templates, 'EXECUTIVE SUMMARY', 'ANALYSIS', 'NEXT STEPS', or support ticket jargon for casual conversations.\n"
    "- Length: Keep replies concise and easy to read on mobile (1-3 short paragraphs max).\n"
    "- Personality: Show humor, curiosity, and warmth. If the user asks why you responded weirdly or made a mistake, be candid, lighthearted, and self-aware."
)

DEFAULT_RESEARCH_PROMPT = (
    "You are Karna, an intelligent and sharp personal AI assistant. "
    "Present research, data, and answers clearly, engagingly, and beautifully.\n\n"
    "Presentation Rules:\n"
    "- Structure: Give a direct, engaging answer followed by organized key points.\n"
    "- Formatting: Use clean bullet points, highlights, or cards for dates, prices, and locations. Do NOT use stiff bureaucratic labels like 'EXECUTIVE SUMMARY' or 'NEXT STEPS'.\n"
    "- Links: Include direct, clickable markdown links [Title](URL) for sources and official registrations.\n"
    "- Tone: Helpful, knowledgeable, and articulate, yet conversational and friendly."
)


def get_dynamic_system_prompt(is_research: bool = False) -> str:
    """Build the system prompt with live temporal context and appropriate conversational persona."""
    temporal_block = build_system_temporal_prompt()
    base_prompt = DEFAULT_RESEARCH_PROMPT if is_research else DEFAULT_CONVERSATIONAL_PROMPT
    return f"{base_prompt}\n\n{temporal_block}"



class MessageSender(Protocol):
    """Interface any channel sender must implement."""

    async def send_text(self, to: str, text: str) -> Optional[str]:
        """Send a text message and return the channel message id, or None."""


class ChatService:
    """Orchestrates the full inbound-message processing pipeline."""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        sender: Optional[MessageSender] = None,
        tool_router: Optional[ToolRouter] = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.sender = sender
        self.tool_router = tool_router or default_tool_router
        self.max_history = config.max_history_messages
        self.session_timeout_seconds = config.session_timeout_seconds

    async def process_inbound(
        self,
        *,
        sender_id: str,
        external_message_id: str,
        text: str,
        timestamp: Optional[str] = None,
        request_id: str = "system",
        sender: Optional[MessageSender] = None,
    ) -> dict:
        """Run the full pipeline for one inbound message.

        Returns a dict describing the outcome (for logging/tests).
        """
        result: dict = {
            "sender_id": sender_id,
            "external_message_id": external_message_id,
            "authorized": False,
            "duplicate": False,
            "llm_response": None,
            "message_id": None,
            "sent": False,
            "error": None,
        }

        # 1. Sender authorization (channel-agnostic).
        from app.security.authorization import is_sender_authorized

        if not is_sender_authorized(sender_id):
            result["error"] = "unauthorized sender"
            logger.warning(
                "Unauthorized sender ignored: %s",
                sender_id,
                extra={"request_id": request_id, "message_id": external_message_id},
            )
            return result
        result["authorized"] = True

        # 2. Duplicate detection (persisted inbound id).
        if repository.message_exists(external_message_id):
            result["duplicate"] = True
            logger.info(
                "Duplicate inbound message ignored: %s",
                external_message_id,
                extra={"request_id": request_id, "message_id": external_message_id},
            )
            return result

        # 3. Store incoming message.
        repository.get_or_create_sender(sender_id)
        repository.create_message(
            external_message_id=external_message_id,
            sender_id=sender_id,
            direction="inbound",
            text=text,
            timestamp=timestamp,
            status="received",
        )

        # 4. Retrieve conversation history for the active session.
        # Starting a new conversation is timing-driven: if the idle gap since the last message
        # exceeds session_timeout_seconds, get_active_session_history returns [],
        # starting fresh without carrying over old topics or search queries.
        ref_time = repository.parse_db_timestamp(timestamp) or datetime.now(timezone.utc)
        history = repository.get_active_session_history(
            sender_id=sender_id,
            limit=self.max_history,
            timeout_seconds=self.session_timeout_seconds,
            reference_time=ref_time,
            exclude_external_id=external_message_id,
        )

        # Extract previous inbound user message within the active session for follow-ups (e.g. "use searching")
        previous_user_message: Optional[str] = None
        for entry in reversed(history):
            if entry["direction"] == "inbound":
                previous_user_message = entry["text"]
                break

        # 5. Route to tools if needed (web search / webpage extraction).
        tool_result = await self.tool_router.route_and_execute(
            text,
            previous_query=previous_user_message,
        )
        result["tool_result"] = {
            "tool_name": tool_result.tool_name,
            "input_value": tool_result.input_value,
        }

        # 6. Call local LLM with active session history and grounded context.
        # Use active session history entries and compact past assistant replies to keep context concise
        llm_messages: List[dict] = []
        for entry in history:
            role = "assistant" if entry["direction"] == "outbound" else "user"
            content = entry["text"]
            # Cleanly compact older assistant replies without injecting artificial meta-tags
            if role == "assistant" and len(content) > 280:
                first_part = content.split("\n\n")[0].strip()
                if len(first_part) > 280:
                    first_part = first_part[:280].rsplit(" ", 1)[0] + "..."
                content = first_part
            llm_messages.append({"role": role, "content": content})

        effective_user_text = text
        if tool_result.context_text:
            if tool_result.tool_name == "daily_briefing":
                effective_user_text = (
                    f"{text}\n\n"
                    f"[Indexed Intelligence & Daily Digest Context]:\n"
                    f"{tool_result.context_text}\n\n"
                    f"Instructions:\n"
                    f"1. Deliver a crisp, engaging daily intelligence briefing based directly on the indexed records above.\n"
                    f"2. Group items clearly by topic or source and highlight key insights.\n"
                    f"3. Keep paragraphs short (1-2 sentences) and format as clean bullet cards for mobile readability.\n"
                    f"4. Always include clickable markdown links [Title](URL) for each item.\n"
                    f"5. Do NOT say you don't have a daily briefing; you DO have the fresh intelligence provided above."
                )
            else:
                effective_user_text = (
                    f"{text}\n\n"
                    f"[Factual Research Context]:\n"
                    f"{tool_result.context_text}\n\n"
                    f"Instructions:\n"
                    f"1. Synthesize the research context above to directly address the user request.\n"
                    f"2. Keep paragraphs short (2-3 sentences max) and use clean bullet points or cards for mobile readability.\n"
                    f"3. Avoid excessively long lines of unbroken text so messages read well on mobile screens.\n"
                    f"4. Only mention active or upcoming events; do not present expired events as upcoming.\n"
                    f"5. Always include clickable markdown links [Title](URL) for event links and sources."
                )

        llm_messages.append({"role": "user", "content": effective_user_text})

        is_research = bool(tool_result.context_text)
        generation_tokens = 400 if is_research else 180
        temperature = 0.3 if is_research else 0.7

        try:
            reply = await self.llm.generate(
                messages=llm_messages,
                system_prompt=get_dynamic_system_prompt(is_research=is_research),
                max_tokens=generation_tokens,
                temperature=temperature,
            )
        except LLMClientError as exc:
            result["error"] = f"llm error: {exc}"
            logger.error(
                "LLM generation failed: %s",
                exc,
                extra={"request_id": request_id, "message_id": external_message_id},
            )
            repository.mark_processing(external_message_id, "failed")
            return result

        result["llm_response"] = reply

        # 6. Store generated response (outbound).
        repository.create_message(
            external_message_id=None,
            sender_id=sender_id,
            direction="outbound",
            text=reply,
            timestamp=None,
            status="pending",
        )

        # 7. Send response through the configured channel.
        active_sender = sender if sender is not None else self.sender
        message_id: Optional[str] = None
        if active_sender is not None:
            message_id = await active_sender.send_text(to=sender_id, text=reply)
        result["message_id"] = message_id
        result["sent"] = bool(message_id)

        # 8. Record delivery result.
        if message_id:
            repository.mark_processing(external_message_id, "delivered")
            logger.info(
                "Message processed and delivered: %s",
                external_message_id,
                extra={"request_id": request_id, "message_id": external_message_id},
            )
        else:
            repository.mark_processing(external_message_id, "send_failed")
            logger.warning(
                "Message processed but send failed: %s",
                external_message_id,
                extra={"request_id": request_id, "message_id": external_message_id},
            )

        return result