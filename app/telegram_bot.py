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


def _build_client() -> TelegramClient:
    return TelegramClient()


def build_application() -> Application:
    """Build the PTB Application and register handlers."""
    if not config.is_telegram_configured():
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    builder = ApplicationBuilder().token(config.telegram_bot_token)
    application = builder.build()

    # Command handlers.
    application.add_handler(CommandHandler("start", _start_command))
    application.add_handler(CommandHandler("id", _start_command))
    application.add_handler(CommandHandler("reset", _start_command))
    application.add_handler(CommandHandler("status", _start_command))

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
