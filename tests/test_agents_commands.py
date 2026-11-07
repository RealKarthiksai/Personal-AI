"""Tests for DIRECT agent slash commands (asserting 0 LLM calls)."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import yaml

from app.agents.commands import (
    handle_agent_status_command,
    handle_job_detail_command,
    handle_jobs_command,
    handle_panic_command,
    handle_stop_command,
    handle_workspaces_command,
)
from app.agents.models import AgentJob, AgentKind, JobMode, JobStatus
from app.agents.policy import set_panic
from app.config import config
from app.database import database
from app.services.tool_router import ResponseMode


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up isolated test database and workspace configuration."""
    with tempfile.NamedTemporaryFile(suffix=".db") as db_f, tempfile.TemporaryDirectory() as tmpdir:
        db_path = db_f.name
        monkeypatch.setattr(database.config, "database_url", f"sqlite:///{db_path}")
        database._init_lock = False
        database.init_db()

        ws_dir = Path(tmpdir) / "karna"
        ws_dir.mkdir()
        (ws_dir / ".git").mkdir()

        cfg_content = {
            "workspaces": [
                {
                    "alias": "karna",
                    "path": str(ws_dir),
                    "cloud_ok": True,
                    "autonomous_ok": True,
                    "allow_non_git": False,
                }
            ]
        }
        cfg_file = Path(tmpdir) / "agent_workspaces.yml"
        cfg_file.write_text(yaml.safe_dump(cfg_content), encoding="utf-8")

        monkeypatch.setattr(config, "agent_workspaces_file", str(cfg_file))
        monkeypatch.setattr(config, "agents_enabled", True)
        monkeypatch.setattr(config, "agents_panic", False)
        monkeypatch.setattr(config, "allowed_agent_user_ids", [12345])
        monkeypatch.setattr("app.agents.policy.is_agent_installed", lambda a: True)
        set_panic(False)

        yield {"ws_dir": ws_dir, "cfg_file": str(cfg_file)}


def test_workspaces_command():
    """Verify /workspaces outputs clean HTML listing with flags."""
    res = handle_workspaces_command()
    assert res.mode == ResponseMode.DIRECT
    assert "📂 <b>Allowlisted Workspaces</b>" in res.direct
    assert "karna" in res.direct
    assert "Cloud allowed" in res.direct


def test_agent_status_command():
    """Verify /agent status outputs system state, panic status, and binary availability."""
    res = handle_agent_status_command()
    assert res.mode == ResponseMode.DIRECT
    assert "🤖 <b>Agent Delegation Status</b>" in res.direct
    assert "🟢 Normal" in res.direct


def test_jobs_and_job_detail_command():
    """Verify /jobs and /job <id> commands."""
    from app.agents.jobs import get_job_manager
    mgr = get_job_manager()

    job_id = str(uuid.uuid4())
    with database.transaction() as conn:
        conn.execute(
            """
            INSERT INTO agent_jobs (
                id, sender_id, channel, agent, workspace_alias, workspace_path,
                mode, autonomous, task_text, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (job_id, "12345", "telegram", "cline", "karna", "/tmp", "read_only", 0, "run pytest", "succeeded"),
        )

    # /jobs
    res = handle_jobs_command(sender_id="12345")
    assert res.mode == ResponseMode.DIRECT
    assert "📋 <b>Recent Agent Jobs</b>" in res.direct
    assert job_id[:8] in res.direct

    # /job <id>
    res_detail = handle_job_detail_command(job_id[:8])
    assert res_detail.mode == ResponseMode.DIRECT
    assert "Agent Job Completed" in res_detail.direct


@pytest.mark.asyncio
async def test_stop_command():
    """Verify /stop cancels an active or queued job."""
    from app.agents.jobs import get_job_manager
    mgr = get_job_manager()

    job_id = str(uuid.uuid4())
    with database.transaction() as conn:
        conn.execute(
            """
            INSERT INTO agent_jobs (
                id, sender_id, channel, agent, workspace_alias, workspace_path,
                mode, autonomous, task_text, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (job_id, "12345", "telegram", "cline", "karna", "/tmp", "read_only", 0, "long job", "queued"),
        )

    res = await handle_stop_command(job_id[:8], sender_id="12345")
    assert res.mode == ResponseMode.DIRECT
    assert "was cancelled" in res.direct


@pytest.mark.asyncio
async def test_panic_command():
    """Verify /panic immediately cancels jobs and sets panic lock."""
    res = await handle_panic_command(sender_id="12345")
    assert res.mode == ResponseMode.DIRECT
    assert "PANIC SWITCH ACTIVATED" in res.direct

    from app.agents.policy import is_panic_active
    assert is_panic_active() is True
