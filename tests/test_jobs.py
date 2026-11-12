import asyncio
import pytest
from app.services.pipeline import jobs

@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.JOBS.clear()
    yield
    jobs.JOBS.clear()

@pytest.mark.asyncio
async def test_jobs_flow(monkeypatch):
    calls_9b = []
    calls_fast = []

    async def mock_plan(text, history):
        needs_search = "search" in text.lower() or "spacex" in text.lower()
        return {"needs_search": needs_search, "queries": ["query 1"] if needs_search else []}

    async def mock_answer(question, history, facts, progress=None):
        calls_9b.append(question)
        if progress:
            progress("searching")
            await asyncio.sleep(0.05)
            progress("writing")
        return ["Here is the search answer [1]."]

    async def mock_reply_direct(text, history, facts, lane="smart"):
        calls_fast.append((text, lane))
        return f"Direct reply to {text}"

    async def mock_rewrite_status(facts):
        calls_fast.append(("status", "fast"))
        return f"Status: {facts}"

    monkeypatch.setattr("app.services.pipeline.jobs.planner.plan", mock_plan)
    monkeypatch.setattr("app.services.pipeline.jobs.answer", mock_answer)
    monkeypatch.setattr("app.services.pipeline.jobs.persona.reply_direct", mock_reply_direct)
    monkeypatch.setattr("app.services.pipeline.jobs.persona.rewrite_status", mock_rewrite_status)

    sent_messages = []
    async def send(msg):
        sent_messages.append(msg)
        return "mid_123"

    async def typing():
        pass

    chat_id = 12345

    # 1. Search question -> spawns background job and sends immediate ACK
    await jobs.on_message(chat_id, "search for SpaceX updates", [], [], send, typing)
    assert len(sent_messages) == 1
    assert any(sent_messages[0].startswith(ack[:10]) for ack in jobs.ACKS)
    assert jobs.active(chat_id) is not None

    # 2. Immediately "hi" -> handled by front desk (fast lane) while job is running!
    await jobs.on_message(chat_id, "hi", [], [], send, typing)
    assert len(sent_messages) == 2
    assert "Direct reply to hi" in sent_messages[1]
    assert calls_fast[-1][1] == "fast"  # confirmed uses fast lane!

    # 3. "done yet?" -> status line
    await jobs.on_message(chat_id, "done yet?", [], [], send, typing)
    assert len(sent_messages) == 3
    assert "Status: Still working" in sent_messages[2]

    # 4. Second search question -> queues behind first
    await jobs.on_message(chat_id, "search for another thing", [], [], send, typing)
    assert len(sent_messages) == 4
    assert "Queued" in sent_messages[3]

    # 5. "cancel" -> cancels active job
    await jobs.on_message(chat_id, "cancel", [], [], send, typing)
    assert len(sent_messages) == 5
    assert "Dropped it." in sent_messages[4]
