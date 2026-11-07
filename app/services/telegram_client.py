"""Asynchronous Telegram Bot API client for sending messages.

Uses the configured TELEGRAM_BOT_TOKEN. Implements bounded retries for
transient failures. The bot token is never logged.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.config import config
from app.formatting.engine import formatting_engine
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

    def _payload(self, chat_id: str, text: str, parse_mode: Optional[str] = "HTML") -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return payload

    async def send_text(
        self,
        chat_id: str,
        text: str,
    ) -> Optional[str]:
        """Send a text message, formatting into platform-compliant chunks.

        If the message exceeds the message length limit (3500 chars), it is
        automatically split into two or more sequential messages.
        Implements bounded retries for transient failures and rate limits.
        """
        if not self.token:
            logger.warning(
                "Telegram not configured; cannot send message",
                extra={"request_id": "system", "message_id": "-"},
            )
            return None

        # Format message into Telegram HTML chunks (splits if text exceeds limit)
        chunks = formatting_engine.format_message(text, channel="telegram", max_length=3500)
        if not chunks:
            if text:
                chunks = [text]
            else:
                return None

        if len(chunks) > 1:
            logger.info(
                "TelegramClient: message exceeds single message limit (%d chars); sending in %d messages",
                len(text),
                len(chunks),
                extra={"request_id": "system", "message_id": "-"},
            )

        last_message_id: Optional[str] = None
        for idx, chunk in enumerate(chunks):
            if idx > 0:
                await asyncio.sleep(0.3)
            mid = await self._send_chunk(chat_id=chat_id, text=chunk)
            if mid:
                last_message_id = mid
            else:
                return None

        return last_message_id

    async def _send_chunk(
        self,
        chat_id: str,
        text: str,
    ) -> Optional[str]:
        """Send a single chunk with bounded retries and fallback."""
        payload = self._payload(chat_id, text, parse_mode="HTML")
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

    async def send_message_with_keyboard(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict,
        parse_mode: Optional[str] = "HTML",
    ) -> Optional[str]:
        """Send a text message with an inline keyboard attached."""
        if not self.token:
            return None
        payload = self._payload(chat_id, text, parse_mode=parse_mode)
        payload["reply_markup"] = reply_markup
        url = self.base_url

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        res = data.get("result", {})
                        return str(res.get("message_id"))
                logger.warning("Telegram send_message_with_keyboard failed: HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Error in send_message_with_keyboard: %s", e)
        return None

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        reply_markup: Optional[dict] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """Edit an existing Telegram message in-place."""
        if not self.token:
            return False
        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                return resp.status_code == 200
        except Exception as e:
            logger.error("Error in edit_message_text: %s", e)
            return False

    async def send_document(
        self,
        chat_id: str,
        document_path: str,
        caption: Optional[str] = None,
    ) -> Optional[str]:
        """Send a file as a Telegram document attachment."""
        if not self.token:
            return None
        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        try:
            import os
            if not os.path.isfile(document_path):
                logger.warning("send_document: file not found: %s", document_path)
                return None

            filename = os.path.basename(document_path)
            with open(document_path, "rb") as f:
                files = {"document": (filename, f, "text/plain")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                    data["parse_mode"] = "HTML"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, data=data, files=files)
                    if resp.status_code == 200:
                        res = resp.json().get("result", {})
                        return str(res.get("message_id"))
                    logger.warning("Telegram sendDocument failed: HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Error in send_document: %s", e)
        return None