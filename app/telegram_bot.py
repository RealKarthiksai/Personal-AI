"""Telegram bot entry point using asynchronous long polling (getUpdates).

This is a standalone, long-running bot. It does NOT use webhooks or
Cloudflare Tunnel. It reuses the existing LLM client, SQLite database, and
chat processing logic.

Run:
    . /home/vhanghar/venv_waichatbot/bin/activate
    python -m app.telegram_bot

Environment variables (in /home/vhanghar/Karna/.env):
    TELEGRAM_BOT_TOKEN         - required Telegram bot token
    TELEGRAM_ALLOWED_USER_IDS  - comma-separated allowed Telegram user IDs
    LLM_BASE_URL               - local llama.cpp endpoint
    DATABASE_URL               - SQLite path
    MAX_HISTORY_MESSAGES       - conversation history window
    REQUEST_TIMEOUT_SECONDS    - HTTP timeout
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import config
from app.database import database
from app.services.chat_service import ChatService
from app.services.telegram_client import TelegramClient
from app.services.telegram_handler import (
    handle_command,
    handle_text_message,
    parse_update,
)
from app.utils.logging import configure_logging, get_logger, redact

configure_logging(level=logging.INFO)
logger = get_logger("app.telegram_bot")


class _SenderAdapter:
    """Adapts TelegramClient to the ChatService MessageSender protocol.

    `to` is the Telegram chat id (string).
    """

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def send_text(self, to: str, text: str) -> Optional[str]:
        return await self._client.send_text(chat_id=to, text=text)

    async def send_chat_action(self, to: str, action: str = "typing") -> bool:
        return await self._client.send_chat_action(chat_id=to, action=action)

    async def send_message_with_keyboard(
        self, to: str, text: str, reply_markup: dict, parse_mode: Optional[str] = "HTML"
    ) -> Optional[str]:
        return await self._client.send_message_with_keyboard(
            chat_id=to, text=text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    async def edit_message_text(
        self, to: str, message_id: str, text: str, reply_markup: Optional[dict] = None, parse_mode: Optional[str] = "HTML"
    ) -> bool:
        return await self._client.edit_message_text(
            chat_id=to, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    async def send_document(
        self, to: str, document_path: str, caption: Optional[str] = None
    ) -> Optional[str]:
        return await self._client.send_document(chat_id=to, document_path=document_path, caption=caption)


# Global references for graceful shutdown.
_application: Optional[Application] = None
async def _command_dispatcher(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    service: ChatService,
    sender,
) -> None:
    """Route an incoming update to command or text handling."""
    request_id = str(update.update_id if update.update_id else "system")
    raw = update.to_dict() if update else {}
    parsed = parse_update(raw)
    if parsed is None:
        return

    from app.security.authorization import is_telegram_user_authorized

    if not is_telegram_user_authorized(parsed.user_id):
        logger.warning(
            "Unauthorized Telegram user ignored: %s",
            parsed.user_id,
            extra={"request_id": request_id, "message_id": str(parsed.message_id)},
        )
        return

    if parsed.is_command:
        await handle_command(
            update=parsed,
            service=service,
            sender=sender,
            request_id=request_id,
        )
    else:
        await sender.send_chat_action(to=parsed.chat_id, action="typing")
        await handle_text_message(
            update=parsed,
            service=service,
            sender=sender,
            request_id=request_id,
        )


async def _start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _dispatch(update, context)


async def _text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _dispatch(update, context)


async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _service is None or _application is None:
        return
    sender = _SenderAdapter(_build_client())
    await _command_dispatcher(update, context, _service, sender)


async def _callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram inline keyboard button taps."""
    query = update.callback_query
    if query is None:
        return
    data = query.data or ""
    user_id = str(query.from_user.id)

    from app.security.authorization import is_telegram_user_authorized
    try:
        sender_int = int(user_id)
        if not is_telegram_user_authorized(sender_int):
            await query.answer("Unauthorized", show_alert=True)
            return
    except ValueError:
        await query.answer("Unauthorized", show_alert=True)
        return

    if data.startswith("agent:"):
        parts = data.split(":")
        if len(parts) == 4:
            _, action, short_id, nonce = parts
            from app.agents.confirmations import consume_confirmation, render_confirmation_card
            from app.agents.policy import get_workspace

            success, updated_job, msg = consume_confirmation(
                short_id=short_id,
                nonce=nonce,
                clicking_user_id=user_id,
                action=action,
            )
            await query.answer(msg)

            if success and updated_job:
                if action == "mode":
                    ws = get_workspace(updated_job.workspace_alias)
                    if ws:
                        new_text, new_kb = render_confirmation_card(updated_job, ws, nonce)
                        await query.edit_message_text(text=new_text, parse_mode="HTML", reply_markup=new_kb)
                elif action == "conf":
                    status_line = f"✅ <b>Job Confirmed & Queued</b> (ID: <code>{updated_job.id[:8]}</code>)\n\nRunning in background..."
                    await query.edit_message_text(text=status_line, parse_mode="HTML")
                    from app.agents.jobs import get_job_manager
                    asyncio.create_task(get_job_manager().dispatch_queued_job(updated_job.id))
                elif action == "canc":
                    status_line = f"❌ <b>Job Cancelled</b> (ID: <code>{updated_job.id[:8]}</code>)"
                    await query.edit_message_text(text=status_line, parse_mode="HTML")
        else:
            await query.answer("Malformed callback payload")


def _build_client() -> TelegramClient:
    return TelegramClient()


def build_application() -> Application:
    """Build the PTB Application and register handlers."""
    if not config.is_telegram_configured():
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    builder = ApplicationBuilder().token(config.telegram_bot_token)
    application = builder.build()

    # Command handlers.
    for cmd in (
        "start", "help", "id", "reset", "status", "search", "read", "briefing", "digest",
        "feeds", "subscriptions", "watches", "monitors", "diff", "versions",
        "memory", "memories", "pin", "unpin", "forget", "forget_all",
        "export", "privacy", "link", "memory_debug",
        "agent", "jobs", "job", "stop", "panic", "workspaces", "resume",
    ):
        application.add_handler(CommandHandler(cmd, _start_command))

    # Inline button callback queries
    application.add_handler(CallbackQueryHandler(_callback_query))

    # Catch-all for any other slash command
    application.add_handler(MessageHandler(filters.COMMAND, _start_command))

    # Text message handler (non-command).
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_message))

    return application


async def _run_polling() -> None:
    """Run long polling until cancelled."""
    global _application, _service
    application = build_application()
    _application = application
    _service = ChatService(sender=_SenderAdapter(_build_client()))

    # Initialize the database and PTB application.
    database.init_db()
    await application.initialize()
    await application.start()

    logger.info(
        "Telegram bot starting (long polling) | llm=%s | telegram=%s",
        "configured" if config.is_llm_configured() else "NOT configured",
        "configured" if config.is_telegram_configured() else "NOT configured",
        extra={"request_id": "system", "message_id": "system"},
    )

    # Start polling (getUpdates long polling).
    await application.updater.start_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=True,
    )

    # Wait until shutdown is requested.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, OSError):
            # Signal handlers not available on this platform (e.g. Windows).
            pass

    await stop_event.wait()

    logger.info("Shutdown signal received; stopping Telegram bot...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    _application = None
    _service = None
    logger.info("Telegram bot stopped.")


def main() -> None:
    if not config.is_telegram_configured():
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured. Set it in .env and rerun.",
        )
        sys.exit(1)

    try:
        asyncio.run(_run_polling())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
_service: Optional[ChatService] = None
