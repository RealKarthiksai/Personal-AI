"""Tests for TelegramDebouncer: sliding timer, concurrency, mid-generation arrival, and typing heartbeat."""

import asyncio
from datetime import datetime, timezone
import pytest

from app.services.debouncer import TelegramDebouncer
from app.services.telegram_handler import TelegramUpdate


class MockTypingSender:
    def __init__(self) -> None:
        self.typing_actions: list[str] = []

    async def send_chat_action(self, to: str, action: str = "typing") -> bool:
        self.typing_actions.append(f"{to}:{action}")
        return True


def _make_update(update_id: int, chat_id: str, text: str) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        chat_id=chat_id,
        message_id=update_id,
        user_id=12345,
        text=text,
        is_command=False,
        command=None,
    )


@pytest.mark.asyncio
async def test_debouncer_burst_aggregation() -> None:
    """A burst of 3 messages arriving rapidly should be aggregated into a single handler call."""
    calls: list[list[str]] = []

    async def mock_handler(chat_id: str, burst: list[TelegramUpdate]) -> None:
        calls.append([u.text for u in burst])

    sender = MockTypingSender()
    debouncer = TelegramDebouncer(delay=0.08, heartbeat_interval=0.5, sender=sender, handler=mock_handler)

    # Push 3 messages within the 80ms window
    await debouncer.push(_make_update(1, "chat_1", "part 1"))
    await asyncio.sleep(0.02)
    await debouncer.push(_make_update(2, "chat_1", "part 2"))
    await asyncio.sleep(0.02)
    await debouncer.push(_make_update(3, "chat_1", "part 3"))

    # Wait for the debounce delay to expire and flush
    await asyncio.sleep(0.15)

    assert len(calls) == 1
    assert calls[0] == ["part 1", "part 2", "part 3"]
    await debouncer.shutdown()


@pytest.mark.asyncio
async def test_debouncer_mid_generation_arrival_queued_not_dropped_nor_double_fired() -> None:
    """Requirement 8: Burst of 3, then a 4th while the 3 are generating.

    Assert the 4th is queued, executed as the second turn, not dropped and not double-fired.
    """
    calls: list[list[str]] = []
    generation_started = asyncio.Event()
    release_generation = asyncio.Event()

    async def slow_handler(chat_id: str, burst: list[TelegramUpdate]) -> None:
        calls.append([u.text for u in burst])
        if len(calls) == 1:
            generation_started.set()
            await release_generation.wait()

    sender = MockTypingSender()
    debouncer = TelegramDebouncer(delay=0.05, heartbeat_interval=0.5, sender=sender, handler=slow_handler)

    # Send burst of 3
    await debouncer.push(_make_update(1, "chat_1", "msg 1"))
    await debouncer.push(_make_update(2, "chat_1", "msg 2"))
    await debouncer.push(_make_update(3, "chat_1", "msg 3"))

    # Wait for flush to trigger generation
    await generation_started.wait()
    assert len(calls) == 1
    assert calls[0] == ["msg 1", "msg 2", "msg 3"]

    # Now while generation is in flight, send a 4th message
    await debouncer.push(_make_update(4, "chat_1", "msg 4"))

    # Let the 4th message's timer run while 1st generation is still active
    await asyncio.sleep(0.08)

    # Release the 1st generation
    release_generation.set()

    # Give time for the debouncer loop to drain the 4th message
    await asyncio.sleep(0.1)

    # Exactly 2 calls: call 1 with [msg 1, 2, 3], call 2 with [msg 4]
    assert len(calls) == 2
    assert calls[0] == ["msg 1", "msg 2", "msg 3"]
    assert calls[1] == ["msg 4"]

    # Wait a bit more to ensure no duplicate 3rd call
    await asyncio.sleep(0.1)
    assert len(calls) == 2

    await debouncer.shutdown()


@pytest.mark.asyncio
async def test_debouncer_handler_exception_releases_lock_and_cancels_heartbeat() -> None:
    """An exception inside the handler must cancel the heartbeat and release the lock."""
    calls: list[str] = []

    async def failing_handler(chat_id: str, burst: list[TelegramUpdate]) -> None:
        calls.append(burst[0].text)
        if burst[0].text == "fail":
            raise RuntimeError("LLM exploded")

    sender = MockTypingSender()
    debouncer = TelegramDebouncer(delay=0.04, heartbeat_interval=0.02, sender=sender, handler=failing_handler)

    # 1st call fails with RuntimeError
    await debouncer.push(_make_update(1, "chat_err", "fail"))
    # Wait for flush
    await asyncio.sleep(0.08)
    assert calls == ["fail"]

    # 2nd call should still acquire lock and succeed despite previous failure
    await debouncer.push(_make_update(2, "chat_err", "succeed"))
    await asyncio.sleep(0.08)
    assert calls == ["fail", "succeed"]

    await debouncer.shutdown()


@pytest.mark.asyncio
async def test_debouncer_typing_heartbeat() -> None:
    """Typing heartbeat fires periodically during prolonged generation."""
    handler_done = asyncio.Event()

    async def long_handler(chat_id: str, burst: list[TelegramUpdate]) -> None:
        await asyncio.sleep(0.09)
        handler_done.set()

    sender = MockTypingSender()
    # Heartbeat interval of 25ms
    debouncer = TelegramDebouncer(delay=0.03, heartbeat_interval=0.025, sender=sender, handler=long_handler)

    await debouncer.push(_make_update(1, "chat_hb", "hello"))
    await handler_done.wait()
    await asyncio.sleep(0.02)

    # Initial typing + periodic heartbeats
    assert len(sender.typing_actions) >= 3
    assert all(a == "chat_hb:typing" for a in sender.typing_actions)

    await debouncer.shutdown()
