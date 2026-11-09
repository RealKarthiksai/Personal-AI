"""Sliding-window debouncer and concurrent burst aggregator for Telegram messages.

Collects multi-part user messages into a unified conversational turn while
strictly ensuring:
1. Sliding delay timer only cancels the sleep timer, NEVER active LLM generation.
2. Per-chat exclusive lock prevents overlapping generation races.
3. Mid-generation arrivals are queued in the buffer and processed as the next turn.
4. Typing heartbeat is cancellable and always cleaned up in try/finally.
5. Delay and heartbeat intervals are fully injectable for unit testing.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

from app.services.telegram_handler import TelegramUpdate
from app.utils.logging import get_logger

logger = get_logger("app.debouncer")


class TypingSender(Protocol):
    """Protocol for sending typing chat action."""

    async def send_chat_action(self, to: str, action: str = "typing") -> Optional[bool]:
        """Send chat action e.g. typing."""


TelegramBurstHandler = Callable[..., Awaitable[Any]]


class TelegramDebouncer:
    """Debounces fast bursts of Telegram messages per chat and drains them sequentially."""

    def __init__(
        self,
        delay: float = 1.1,
        heartbeat_interval: float = 4.0,
        sender: Optional[Any] = None,
        handler: Optional[TelegramBurstHandler] = None,
    ) -> None:
        self.delay = delay
        self.heartbeat_interval = heartbeat_interval
        self.sender = sender
        self.handler = handler

        self._buffers: Dict[str, List[TelegramUpdate]] = defaultdict(list)
        self._timers: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._state_lock = asyncio.Lock()

    def set_handler(self, handler: TelegramBurstHandler) -> None:
        """Inject or update the burst handler."""
        self.handler = handler

    def set_sender(self, sender: Any) -> None:
        """Inject or update the message sender."""
        self.sender = sender

    async def push(self, update: TelegramUpdate, request_id: str = "system") -> None:
        """Receive an incoming TelegramUpdate, buffer it, and schedule/slide the flush timer."""
        chat_id = update.chat_id

        # 1. Send immediate typing indicator on arrival
        if self.sender:
            try:
                await self.sender.send_chat_action(to=chat_id, action="typing")
            except Exception as exc:
                logger.debug("Failed sending initial typing action to %s: %s", chat_id, exc)

        async with self._state_lock:
            # 2. Add message to chat buffer
            self._buffers[chat_id].append(update)

            # 3. Slide the timer: cancel only the pending sleep timer (never active generation)
            existing_timer = self._timers.get(chat_id)
            if existing_timer and not existing_timer.done():
                existing_timer.cancel()

            # 4. Start fresh sleep timer task
            self._timers[chat_id] = asyncio.create_task(
                self._wait_and_flush(chat_id),
                name=f"debounce-{chat_id}",
            )

    async def _wait_and_flush(self, chat_id: str) -> None:
        """Sleep for debounce delay. If cancelled, safely exits without flushing."""
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            # A new message arrived during the delay window; cancel the sleep only.
            return

        # Delay completed cleanly; flush the buffered messages for this chat.
        await self._flush(chat_id)

    async def _flush(self, chat_id: str) -> None:
        """Acquire per-chat lock and sequentially drain all messages in the buffer."""
        lock = self._locks[chat_id]

        async with lock:
            while True:
                burst: List[TelegramUpdate] = []
                async with self._state_lock:
                    if self._buffers[chat_id]:
                        burst = list(self._buffers[chat_id])
                        self._buffers[chat_id].clear()

                if not burst:
                    break

                await self._process_burst(chat_id, burst)

    async def _process_burst(self, chat_id: str, burst: List[TelegramUpdate]) -> None:
        """Execute the handler on a burst with typing heartbeat and try/finally cleanup."""
        if not self.handler:
            return

        stop_heartbeat = asyncio.Event()
        heartbeat_task: Optional[asyncio.Task] = None

        if self.sender and self.heartbeat_interval > 0:
            heartbeat_task = asyncio.create_task(
                self._typing_heartbeat(chat_id, stop_heartbeat),
                name=f"heartbeat-{chat_id}",
            )

        try:
            await self.handler(chat_id=chat_id, burst=burst)
        finally:
            stop_heartbeat.set()
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _typing_heartbeat(self, chat_id: str, stop_event: asyncio.Event) -> None:
        """Periodically refresh the Telegram typing status until stopped."""
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.heartbeat_interval)
                except asyncio.TimeoutError:
                    if self.sender and not stop_event.is_set():
                        try:
                            await self.sender.send_chat_action(to=chat_id, action="typing")
                        except Exception as exc:
                            logger.debug("Heartbeat typing failed for %s: %s", chat_id, exc)
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        """Cancel all pending sleep timer tasks."""
        async with self._state_lock:
            for task in self._timers.values():
                if not task.done():
                    task.cancel()
            self._timers.clear()
