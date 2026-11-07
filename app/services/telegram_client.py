"""Asynchronous Telegram Bot API client for sending messages.

Uses the configured TELEGRAM_BOT_TOKEN. Implements bounded retries for
transient failures. The bot token is never logged.
"""

from __future__ import annotations

from typing import Optional

import httpx

from app.config import config
from app.utils.logging import get_logger, redact

logger = get_logger("app.telegram_client")


class TelegramClientError(Exception):
    """Base error for Telegram client failures."""


class TelegramAPIError(TelegramClientError):
    """The Telegram Bot API returned an error response."""


class TelegramClient:
    """Client for sending text messages via the Telegram Bot API."""

    def __init__(self) -> None:
        self.token = config.telegram_bot_token
        self.timeout = config.request_timeout_seconds
        self.max_retries = 3

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}/sendMessage"

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _payload(self, chat_id: str, text: str) -> dict:
        return {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

    async def send_text(
        self,
        chat_id: str,
        text: str,
    ) -> Optional[str]:
        """Send a text message. Returns the Telegram message id on success.

        Implements bounded retries (max_retries) for transient failures and
        rate-limited responses (429, 5xx). Returns None if all attempts fail.
        """
        if not self.token:
            logger.warning(
                "Telegram not configured; cannot send message",
                extra={"request_id": "system", "message_id": "-"},
            )
            return None

        payload = self._payload(chat_id, text)
        url = self.base_url

        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=self._headers())
            except httpx.RequestError as exc:
                last_error = str(exc)
                logger.warning(
                    "Telegram request error (attempt %d/%d): %s",
                    attempt, self.max_retries, last_error,
                    extra={"request_id": "system", "message_id": "-"},
                )
                if attempt == self.max_retries:
                    break
                continue

            if resp.status_code == 429:
                last_error = "rate limited"
                logger.warning(
                    "Telegram rate limited (attempt %d/%d)",
                    attempt, self.max_retries,
                    extra={"request_id": "system", "message_id": "-"},
                )
                if attempt == self.max_retries:
                    break
                continue

            if 500 <= resp.status_code < 600:
                last_error = f"server error HTTP {resp.status_code}"
                logger.warning(
                    "Telegram server error (attempt %d/%d): %s",
                    attempt, self.max_retries, resp.status_code,
                    extra={"request_id": "system", "message_id": "-"},
                )
                if attempt == self.max_retries:
                    break
                continue

            if resp.status_code >= 400:
                last_error = f"client error HTTP {resp.status_code}"
                if payload.get("parse_mode") and "parse entities" in resp.text.lower():
                    logger.warning(
                        "Telegram Markdown parsing failed; retrying without parse_mode",
                        extra={"request_id": "system", "message_id": "-"},
                    )
                    payload.pop("parse_mode", None)
                    continue
                logger.warning(
                    "Telegram client error HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                    extra={"request_id": "system", "message_id": "-"},
                )
                return None

            try:
                data = resp.json()
            except ValueError:
                last_error = "invalid JSON response"
                logger.warning(
                    "Telegram returned invalid JSON",
                    extra={"request_id": "system", "message_id": "-"},
                )
                return None

            if not data.get("ok"):
                last_error = f"Telegram API error: {data.get('description')}"
                logger.warning(
                    "Telegram API returned ok=false: %s",
                    data.get("description"),
                    extra={"request_id": "system", "message_id": "-"},
                )
                return None

            result = data.get("result")
            if isinstance(result, dict):
                message_id = result.get("message_id")
                if message_id:
                    logger.info(
                        "Telegram message sent message_id=%s",
                        message_id,
                        extra={"request_id": "system", "message_id": "-"},
                    )
                    return str(message_id)

            last_error = "no message id in response"
            logger.warning(
                "Telegram response missing message id",
                extra={"request_id": "system", "message_id": "-"},
            )
            return None

        logger.error(
            "Telegram send failed after %d attempts: %s",
            self.max_retries, last_error,
            extra={"request_id": "system", "message_id": "-"},
        )
        return None

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> bool:
        """Send a chat action (e.g. typing) to Telegram. Best effort, no retries."""
        if not self.token:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendChatAction"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    url,
                    json={"chat_id": chat_id, "action": action},
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False