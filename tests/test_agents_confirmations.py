"""Tests for agent task confirmation store, inline cards, and callback state transitions."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.confirmations import (
    consume_confirmation,
    create_confirmation,
    render_confirmation_card,
)
from app.agents.models import AgentJob, AgentKind, JobMode, JobStatus, WorkspaceConfig
from app.database import database


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Use an isolated in-memory or temporary SQLite database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_path = f.name
        monkeypatch.setattr(database.config, "database_url", f"sqlite:///{db_path}")
        database._init_lock = False
        database.init_db()
        yield db_path


def test_create_confirmation_and_render_card():
    """Verify confirmation record creation, nonce length, and card HTML rendering."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="run tests & fix bugs",
    )
    workspace = WorkspaceConfig(
        alias="karna",
        path="/home/user/karna",
        cloud_ok=False,
        autonomous_ok=True,
    )

    record, short_id = create_confirmation(job, ttl_seconds=300)
    assert record.job_id == job_id
    assert record.sender_id == "12345"
    assert len(record.nonce) == 8
    assert short_id == job_id[:8]

    # Render card
    text, keyboard = render_confirmation_card(job, workspace, record.nonce)
    assert "⚡ <b>Agent Task Dispatch</b>" in text
    assert "🔒 Local" in text
    assert "run tests &amp; fix bugs" in text  # HTML escaped
    assert "read-only" in text

    # Verify callback_data lengths
    buttons = keyboard["inline_keyboard"]
    for row in buttons:
        for btn in row:
            cb_data = btn["callback_data"]
            assert len(cb_data) < 64, f"Callback data too long ({len(cb_data)} chars): {cb_data}"
            assert cb_data.startswith("agent:")


def test_consume_confirmation_flow_and_double_tap():
    """Test confirming a job and rejecting double taps."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="refactor scheduler",
    )
    record, short_id = create_confirmation(job, ttl_seconds=300)

    # 1. Successful confirmation tap by author
    ok, updated_job, msg = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="conf",
    )
    assert ok is True
    assert updated_job.status == JobStatus.QUEUED
    assert updated_job.confirmed_at is not None
    assert "confirmed and queued" in msg.lower()

    # 2. Second tap (double tap) must be rejected
    ok2, _, msg2 = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="conf",
    )
    assert ok2 is False
    assert "already been used" in msg2.lower()


def test_consume_confirmation_wrong_user():
    """Tapping confirmation by a different user must be rejected."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.ANTIGRAVITY,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="investigate logs",
    )
    record, short_id = create_confirmation(job, ttl_seconds=300)

    ok, _, msg = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="99999",  # wrong user
        action="conf",
    )
    assert ok is False
    assert "only the user who initiated" in msg.lower()


def test_consume_confirmation_cancellation():
    """Cancelling a job transitions it to cancelled state."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="delete tests",
    )
    record, short_id = create_confirmation(job, ttl_seconds=300)

    ok, updated_job, msg = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="canc",
    )
    assert ok is True
    assert updated_job.status == JobStatus.CANCELLED
    assert "cancelled" in msg.lower()


def test_mode_toggle():
    """Toggling mode changes between read_only and edit."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="test toggle",
    )
    record, short_id = create_confirmation(job, ttl_seconds=300)

    ok, updated_job, msg = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="mode",
    )
    assert ok is True
    assert updated_job.mode == JobMode.EDIT

    # Toggle back
    ok2, updated_job2, msg2 = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="mode",
    )
    assert ok2 is True
    assert updated_job2.mode == JobMode.READ_ONLY


def test_expired_confirmation():
    """An expired confirmation is rejected and marked as rejected."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        id=job_id,
        sender_id="12345",
        channel="telegram",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        task_text="old task",
    )
    # TTL of -10 seconds to simulate expiry
    record, short_id = create_confirmation(job, ttl_seconds=-10)

    ok, _, msg = consume_confirmation(
        short_id=short_id,
        nonce=record.nonce,
        clicking_user_id="12345",
        action="conf",
    )
    assert ok is False
    assert "expired" in msg.lower()
