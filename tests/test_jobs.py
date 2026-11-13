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


def test_job_duration_and_completion_tracking() -> None:
    job = jobs.Job(chat_id="test_user", question="test question")
    assert job.duration_s >= 0.0
    assert job.completed_at is None

    time_now = job.started + 1.25
    job.completed_at = time_now
    assert job.duration_s == 1.25


def test_queue_stats_and_clear_all_jobs(monkeypatch) -> None:
    from app.config import config
    monkeypatch.setattr(config, "pipeline_max_concurrent_jobs", 3)

    jobs.clear_all_jobs()
    stats_empty = jobs.get_queue_stats()
    assert stats_empty["active_jobs"] == 0
    assert stats_empty["queued_jobs"] == 0
    assert stats_empty["concurrency_limit"] == 3

    # Add dummy jobs
    j1 = jobs.Job(chat_id="u1", question="q1", stage="searching")
    j2 = jobs.Job(chat_id="u2", question="q2", stage="queued")
    jobs.JOBS["u1"] = [j1]
    jobs.JOBS["u2"] = [j2]

    stats_populated = jobs.get_queue_stats()
    assert stats_populated["active_jobs"] == 1
    assert stats_populated["queued_jobs"] == 1
    assert stats_populated["stages"] == {"searching": 1, "queued": 1}

    # Verify semaphore reflects config limit
    sem = jobs.get_heavy_semaphore()
    assert sem._value == 3

    # Clear all jobs
    jobs.clear_all_jobs()
    assert len(jobs.JOBS) == 0

