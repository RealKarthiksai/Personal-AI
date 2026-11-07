"""Telegram update parsing and command handling.

Parses incoming Telegram Update objects and extracts:
- chat id (sender identifier)
- message id (for duplicate detection)
- user id (for authorization)
- text (message body)
- command (/start, /id, /reset, /status)

The chat service (LLM + SQLite) is invoked through the injected ChatService.
"""

from __future__ import annotations

from typing import Optional

from app.services.chat_service import ChatService
from app.utils.logging import get_logger

logger = get_logger("app.telegram_handler")


class TelegramUpdate:
    """Normalized representation of an incoming Telegram message."""

    def __init__(
        self,
        update_id: int,
        chat_id: str,
        message_id: int,
        user_id: int,
        text: Optional[str],
        is_command: bool,
        command: Optional[str],
    ) -> None:
        self.update_id = update_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.user_id = user_id
        self.text = text
        self.is_command = is_command
        self.command = command


def parse_update(raw: dict) -> Optional[TelegramUpdate]:
    """Parse a Telegram Update dict into a TelegramUpdate, or None if not a
    text message we can handle."""
    update_id = raw.get("update_id")
    if update_id is None:
        return None

    message = raw.get("message") or raw.get("edited_message")
    if not message:
        return None

    chat = message.get("chat") or {}
    chat_id = str(chat.get("id")) if chat.get("id") is not None else None
    if not chat_id:
        return None

    message_id = message.get("message_id")
    if message_id is None:
        return None

    from_user = message.get("from") or {}
    user_id = from_user.get("id")
    if user_id is None:
        return None

    text = message.get("text")
    if text is None:
        # Ignore non-text messages (media, stickers, etc.) gracefully.
        logger.info(
            "Ignoring non-text Telegram message (update_id=%s)",
            update_id,
            extra={"request_id": str(update_id), "message_id": str(message_id)},
        )
        return None

    is_command = text.startswith("/")
    command = text.split()[0] if is_command else None

    return TelegramUpdate(
        update_id=int(update_id),
        chat_id=chat_id,
        message_id=int(message_id),
        user_id=int(user_id),
        text=text,
        is_command=is_command,
        command=command,
    )


async def handle_command(
    *,
    update: TelegramUpdate,
    service: ChatService,
    sender,
    request_id: str,
) -> dict:
    """Handle a Telegram command. Returns a result dict describing the outcome."""
    command = (update.command or "").lower()
    base_cmd = command.split("@")[0]

    FORWARDED_COMMANDS = {
        "/search", "/read", "/briefing", "/digest",
        "/feeds", "/subscriptions", "/watches", "/monitors", "/diff", "/versions",
        "/status",
        "/memory", "/memories", "/pin", "/unpin", "/forget", "/forget_all",
        "/export", "/privacy", "/link", "/memory_debug",
    }

    if base_cmd in FORWARDED_COMMANDS:
        if hasattr(sender, "send_chat_action"):
            await sender.send_chat_action(to=update.chat_id, action="typing")
        return await handle_text_message(
            update=update,
            service=service,
            sender=sender,
            request_id=request_id,
        )

    if command == "/start":
        reply = (
            "Welcome to Karna, your local AI companion.\n\n"
            "🔍 <b>Tools & Research:</b>\n"
            "/search &lt;query&gt; - search the live web\n"
            "/read &lt;url&gt; - read and summarize a webpage\n"
            "/briefing - daily intelligence digest from indexed feeds\n"
            "/status - live system connectivity & ingestion status\n"
            "/feeds - view subscribed RSS/Atom feeds\n"
            "/watches - view monitored websites\n\n"
            "🧠 <b>Memory & Profile:</b>\n"
            "/memory - view your profile & active memories\n"
            "/pin &lt;id&gt; - protect memory from time decay\n"
            "/unpin &lt;id&gt; - allow normal decay\n"
            "/forget &lt;id&gt; - permanently delete a memory\n"
            "/forget_all - erase all memories and profile\n"
            "/export - export all memories as JSON\n"
            "/privacy - view data retention & privacy policy\n"
            "/link - link identities across Telegram/WhatsApp/Web\n"
            "/memory_debug &lt;query&gt; - preview context injected to model\n\n"
            "⚙️ <b>System:</b>\n"
            "/reset - clear conversation session\n"
            "/id - show your Telegram user ID"
        )
        await sender.send_text(to=update.chat_id, text=reply)
        return {
            "command": command,
            "handled": True,
            "reply": reply,
        }

    if command == "/id":
        reply = f"Your Telegram user ID is: {update.user_id}"
        await sender.send_text(to=update.chat_id, text=reply)
        return {
            "command": command,
            "handled": True,
            "reply": reply,
        }

    if command == "/reset":
        from app.database import repository

        with repository.transaction() as conn:
            conn.execute(
                "DELETE FROM messages WHERE sender_id = ?",
                (update.chat_id,),
            )
        reply = "Your conversation history has been reset."
        await sender.send_text(to=update.chat_id, text=reply)
        return {
            "command": command,
            "handled": True,
            "reply": reply,
        }

    if command == "/status":
        from app.config import config
        from app.ingestion.storage import list_sources

        llm_ok = bool(config.llm_base_url)
        searx_ok = bool(config.searxng_base_url)
        sources = list_sources()
        total_records = sum(s.get("total_records", 0) for s in sources)
        active_sources = [s["name"] for s in sources if s.get("total_records", 0) > 0]
        sources_summary = f"{total_records} records across {len(active_sources)} sources ({', '.join(active_sources)})" if active_sources else "0 records"

        reply = (
            "Karna Status\n"
            f"Local LLM: {'configured' if llm_ok else 'NOT configured'}\n"
            f"Web Search (SearXNG): {'configured' if searx_ok else 'NOT configured'}\n"
            "Web Extractor: Crawl4AI + Playwright\n"
            f"Indexed Intelligence: {sources_summary}\n"
            f"Scheduler: {'enabled' if config.scheduler_enabled else 'disabled'}\n"
            "Channel: Telegram (long polling)\n"
            f"Max history messages: {config.max_history_messages}"
        )
        await sender.send_text(to=update.chat_id, text=reply)
        return {
            "command": command,
            "handled": True,
            "reply": reply,
        }

    # Unknown command.
    reply = f"Unknown command: {command}. Send /start for help."
    await sender.send_text(to=update.chat_id, text=reply)
    return {
        "command": command,
        "handled": True,
        "reply": reply,
    }


async def handle_text_message(
    *,
    update: TelegramUpdate,
    service: ChatService,
    sender,
    request_id: str,
) -> dict:
    """Handle an ordinary text message through the full chat pipeline."""
    # External message id = f"tg:{update_id}" to avoid collisions across channels.
    external_message_id = f"tg:{update.update_id}"
    result = await service.process_inbound(
        sender_id=update.chat_id,
        external_message_id=external_message_id,
        text=update.text,
        request_id=request_id,
        sender=sender,
    )
    return {
        "type": "text",
        "update_id": update.update_id,
        "result": result,
    }