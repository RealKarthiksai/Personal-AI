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

from typing import List, Optional, Protocol

from app.config import config
from app.context.temporal import build_system_temporal_prompt
from app.database import repository
from app.services.llm_client import LLMClient, LLMClientError
from app.services.tool_router import ToolRouter, tool_router as default_tool_router
from app.utils.logging import get_logger

logger = get_logger("app.chat_service")

DEFAULT_SYSTEM_PROMPT = (
    "You are Karna, an intelligent, highly capable personal AI assistant. "
    "Provide well-structured, elegant, and clearly formatted responses similar to modern AI assistants like ChatGPT and Gemini.\n\n"
    "Formatting Guidelines:\n"
    "- Structure: Begin with a direct summary or executive answer.\n"
    "- Presentation: For events, comparisons, or multi-attribute data, use clean Markdown tables or structured bullet points with bold field names.\n"
    "- Key Deadlines: Clearly call out urgent dates, registration deadlines, or requirements.\n"
    "- Links & Citations: Always include direct, clickable markdown links [Title](URL) for sources and registrations.\n"
    "- Tone: Clear, professional, informative, and beautifully formatted with markdown."
)


def get_dynamic_system_prompt() -> str:
    """Build the system prompt with live temporal context, rules, and presentation style."""
    temporal_block = build_system_temporal_prompt()
    return f"{DEFAULT_SYSTEM_PROMPT}\n\n{temporal_block}"



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

        # 4. Retrieve recent conversation history.
        history = repository.get_recent_history(sender_id, self.max_history)

        # Extract previous inbound user message for follow-ups (e.g. "use searching")
        previous_user_message: Optional[str] = None
        for entry in reversed(history):
            if entry["direction"] == "inbound" and entry["text"] != text:
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

        # 6. Call local LLM with conversation history and grounded context.
        llm_messages: List[dict] = []
        for entry in history:
            role = "assistant" if entry["direction"] == "outbound" else "user"
            llm_messages.append({"role": role, "content": entry["text"]})

        effective_user_text = text
        if tool_result.context_text:
            effective_user_text = (
                f"{text}\n\n"
                f"[Factual Research Context]:\n"
                f"{tool_result.context_text}\n\n"
                f"Instructions:\n"
                f"1. Synthesize the research context above to directly address the user request.\n"
                f"2. Format your response beautifully (like ChatGPT/Gemini): start with an executive summary, follow with structured details (use a Markdown table or bold cards for dates, venue, prizes), and highlight key deadlines.\n"
                f"3. Only mention active or upcoming events; do not present expired events as upcoming.\n"
                f"4. Always include clickable markdown links [Title](URL) for event links and sources."
            )

        if not llm_messages or llm_messages[-1]["content"] != text:
            llm_messages.append({"role": "user", "content": effective_user_text})
        else:
            # Replace the last turn's text with the enriched version for LLM inference
            llm_messages[-1]["content"] = effective_user_text

        try:
            reply = await self.llm.generate(
                messages=llm_messages,
                system_prompt=get_dynamic_system_prompt(),
                max_tokens=450,
                temperature=0.3,
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