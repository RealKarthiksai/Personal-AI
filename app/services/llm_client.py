"""Asynchronous LLM client for llama.cpp's OpenAI-compatible API.

Uses the model identifier discovered from the local inference server.
No cloud model fallback is implemented.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import httpx

from app.config import config
from app.utils.logging import get_logger, redact

logger = get_logger("app.llm_client")


class LLMClientError(Exception):
    """Base error for LLM client failures."""


class LLMUnavailableError(LLMClientError):
    """The local LLM endpoint is unreachable."""


class LLMResponseError(LLMClientError):
    """The local LLM returned a malformed or error response."""


class LLMClient:
    """Client for llama.cpp /v1/chat/completions."""

    def __init__(self) -> None:
        self.base_url = config.llm_base_url
        self.model = config.llm_model
        self.api_key = config.llm_api_key
        self.timeout = config.request_timeout_seconds
        self._model_verified: bool = False
        self._lock = asyncio.Lock()
        self._interactive_waiting: int = 0

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {redact(self.api_key)}"
        return headers

    async def check_model_available(self, force: bool = False) -> Optional[str]:
        """Return the configured model id if reachable, else raise."""
        if self._model_verified and self.model and not force:
            return self.model

        if not self.base_url:
            raise LLMUnavailableError("LLM_BASE_URL is not configured")
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
        except httpx.RequestError as exc:
            raise LLMUnavailableError(f"Cannot reach LLM endpoint {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMUnavailableError(
                f"LLM /models returned HTTP {resp.status_code}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMResponseError(f"LLM /models returned invalid JSON: {exc}") from exc
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list) or not models:
            raise LLMResponseError("LLM /models returned no models")
        discovered = models[0].get("id") if isinstance(models[0], dict) else str(models[0])
        if not self.model:
            self.model = discovered
            logger.info(
                "Discovered LLM model: %s", self.model,
                extra={"request_id": "system", "message_id": "system"},
            )
        self._model_verified = True
        return self.model

    async def tokenize(self, text: str) -> int:
        """Count tokens using llama-server /tokenize endpoint with chars/4 fallback."""
        if not self.base_url:
            return max(1, len(text) // 4)
        url = f"{self.base_url}/tokenize"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json={"content": text})
                if resp.status_code == 200:
                    tokens = resp.json().get("tokens", [])
                    return max(1, len(tokens))
        except Exception:
            pass
        return max(1, len(text) // 4)

    async def generate(
        self,
        messages: List[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        presence_penalty: Optional[float] = 0.4,
        frequency_penalty: Optional[float] = 0.4,
        top_p: Optional[float] = 0.9,
        response_format: Optional[dict] = None,
        priority: str = "interactive",
    ) -> str:
        """Generate a completion using the local LLM.

        `priority` can be 'interactive' (preempts background) or 'background'.
        `presence_penalty` and `frequency_penalty` break repetitive token loops in small models.
        """
        if not self.base_url:
            raise LLMUnavailableError("LLM_BASE_URL is not configured")
        if not self._model_verified:
            await self.check_model_available()

        payload_messages: List[dict] = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload: dict = {
            "model": self.model,
            "messages": payload_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        if top_p is not None:
            payload["top_p"] = top_p
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.base_url}/chat/completions"

        # Priority Gate: interactive requests yield no wait; background yields to interactive
        if priority == "background":
            while self._interactive_waiting > 0:
                await asyncio.sleep(0.05)
            await self._lock.acquire()
        else:
            self._interactive_waiting += 1
            try:
                await self._lock.acquire()
            finally:
                self._interactive_waiting = max(0, self._interactive_waiting - 1)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
        except httpx.RequestError as exc:
            raise LLMUnavailableError(f"Cannot reach LLM endpoint {url}: {exc}") from exc
        finally:
            self._lock.release()

        if resp.status_code >= 400:
            raise LLMResponseError(
                f"LLM /chat/completions returned HTTP {resp.status_code}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMResponseError(f"LLM returned invalid JSON: {exc}") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseError("LLM response contained no choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMResponseError("LLM choice is not an object")
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if not content and message.get("reasoning_content"):
                content = message.get("reasoning_content")
        else:
            content = first.get("text")
        if not content:
            raise LLMResponseError("LLM response contained no text content")
        return str(content)