"""Tests for Cline and Antigravity runner command building and output parsing."""

from __future__ import annotations

import uuid

import pytest

from app.agents.models import AgentJob, AgentKind, JobMode
from app.agents.runners.antigravity import AntigravityRunner
from app.agents.runners.cline import ClineRunner


def test_cline_runner_command_building():
    """Verify Cline CLI flag ordering and plan vs edit modes."""
    runner = ClineRunner()

    # 1. Read-only mode
    job_ro = AgentJob(
        id=str(uuid.uuid4()),
        sender_id="123",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.READ_ONLY,
        autonomous=False,
        task_text="analyze codebase",
    )
    cmd_ro = runner.build_command(job_ro, "/bin/cline")
    assert cmd_ro[0] == "/bin/cline"
    assert "-p" in cmd_ro
    assert "--json" in cmd_ro
    assert "-c" in cmd_ro
    assert "/home/user/karna" in cmd_ro
    assert cmd_ro[-1] == "analyze codebase"

    # 2. Edit + Autonomous mode
    job_edit = AgentJob(
        id=str(uuid.uuid4()),
        sender_id="123",
        agent=AgentKind.CLINE,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.EDIT,
        autonomous=True,
        task_text="fix tests",
    )
    cmd_edit = runner.build_command(job_edit, "/bin/cline")
    assert "--auto-approve" in cmd_edit
    assert "true" in cmd_edit
    assert "-p" not in cmd_edit


def test_cline_output_parsing():
    """Verify NDJSON event stream parsing with raw fallback."""
    runner = ClineRunner()
    ndjson = (
        '{"type": "message", "content": "Running test suite"}\n'
        '{"type": "result", "content": "All 10 tests passed successfully."}\n'
    )
    cleaned, summary = runner.parse_output(ndjson)
    assert "Running test suite" in cleaned
    assert "All 10 tests passed successfully." in summary


def test_antigravity_runner_command_building():
    """Verify that all flags strictly precede -p for Antigravity CLI."""
    runner = AntigravityRunner()

    job = AgentJob(
        id=str(uuid.uuid4()),
        sender_id="123",
        agent=AgentKind.ANTIGRAVITY,
        workspace_alias="karna",
        workspace_path="/home/user/karna",
        mode=JobMode.EDIT,
        autonomous=True,
        conversation_id="conv-abc-123",
        task_text="refactor scheduler",
    )
    cmd = runner.build_command(job, "/bin/agy")
    assert cmd[0] == "/bin/agy"
    assert "--add-dir" in cmd
    assert "/home/user/karna" in cmd
    assert "--mode" in cmd
    assert "accept-edits" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--conversation" in cmd
    assert "conv-abc-123" in cmd

    # Crucial rule: -p must be the last flag followed by the prompt
    p_idx = cmd.index("-p")
    assert p_idx == len(cmd) - 2
    assert cmd[-1] == "refactor scheduler"


def test_antigravity_output_parsing():
    """Verify text cleaning and summary extraction."""
    runner = AntigravityRunner()
    raw = (
        "Starting Antigravity agent...\n"
        "Loading workspace /home/user/karna\n"
        "Refactoring complete. 3 files updated.\n"
    )
    cleaned, summary = runner.parse_output(raw)
    assert "Refactoring complete. 3 files updated." in summary
