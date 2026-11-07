"""Tests for agent security policies, workspace allowlist, and permission gating."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import yaml

from app.agents.models import AgentKind, JobMode, WorkspaceConfig
from app.agents.policy import (
    get_workspace,
    is_git_repository,
    is_panic_active,
    load_workspaces,
    set_panic,
    validate_dispatch_policy,
    validate_workspace_path,
)
from app.config import config


@pytest.fixture
def temp_workspace_env():
    """Create a temporary workspace structure with git and non-git dirs and a custom config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        git_ws = tmp_path / "git_project"
        git_ws.mkdir()
        (git_ws / ".git").mkdir()

        non_git_ws = tmp_path / "plain_folder"
        non_git_ws.mkdir()

        outside_dir = tmp_path / "outside_project"
        outside_dir.mkdir()

        cfg_content = {
            "workspaces": [
                {
                    "alias": "git_ws",
                    "path": str(git_ws),
                    "cloud_ok": True,
                    "autonomous_ok": True,
                    "allow_non_git": False,
                },
                {
                    "alias": "local_plain",
                    "path": str(non_git_ws),
                    "cloud_ok": False,
                    "autonomous_ok": False,
                    "allow_non_git": False,
                },
            ]
        }
        cfg_file = tmp_path / "agent_workspaces.yml"
        cfg_file.write_text(yaml.safe_dump(cfg_content), encoding="utf-8")

        yield {
            "cfg_file": str(cfg_file),
            "git_ws": git_ws,
            "non_git_ws": non_git_ws,
            "outside_dir": outside_dir,
            "tmp_path": tmp_path,
        }


def test_load_workspaces(temp_workspace_env):
    """Test loading and canonical realpath resolution of workspaces."""
    cfg_file = temp_workspace_env["cfg_file"]
    workspaces = load_workspaces(cfg_file)
    assert "git_ws" in workspaces
    assert "local_plain" in workspaces
    assert workspaces["git_ws"].cloud_ok is True
    assert workspaces["local_plain"].cloud_ok is False


def test_workspace_traversal_and_symlink_rejection(temp_workspace_env):
    """Test that path traversal and symlink escapes are caught and outside paths rejected."""
    cfg_file = temp_workspace_env["cfg_file"]
    git_ws = temp_workspace_env["git_ws"]
    outside_dir = temp_workspace_env["outside_dir"]

    # Symlink inside git_ws pointing outside
    escape_link = git_ws / "escape_link"
    os.symlink(outside_dir, escape_link)

    # Valid subpath inside git_ws
    subfile = git_ws / "src" / "main.py"
    subfile.parent.mkdir(parents=True, exist_ok=True)
    subfile.write_text("print('hello')", encoding="utf-8")

    assert validate_workspace_path(str(subfile), cfg_file) is not None
    # Escape link resolves to outside_dir, so it should not match git_ws
    assert validate_workspace_path(str(escape_link), cfg_file) is None
    # Path traversal like /git_ws/../outside_dir resolves outside
    traversal = str(git_ws / ".." / "outside_project")
    assert validate_workspace_path(traversal, cfg_file) is None


def test_cloud_policy_antigravity(temp_workspace_env, monkeypatch):
    """Antigravity must be refused on workspaces where cloud_ok=false."""
    monkeypatch.setattr(config, "agents_enabled", True)
    monkeypatch.setattr(config, "agents_panic", False)
    monkeypatch.setattr(config, "allowed_agent_user_ids", [12345])
    monkeypatch.setattr("app.agents.policy.is_agent_installed", lambda a: True)
    set_panic(False)

    workspaces = load_workspaces(temp_workspace_env["cfg_file"])
    local_ws = workspaces["local_plain"]
    git_ws = workspaces["git_ws"]

    # Local workspace has cloud_ok=False -> Antigravity refused
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.ANTIGRAVITY,
        workspace=local_ws,
        mode=JobMode.READ_ONLY,
    )
    assert not ok
    assert "cloud_ok=false" in err
    assert "cloud-backed" in err

    # Git workspace has cloud_ok=True -> Antigravity allowed
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.ANTIGRAVITY,
        workspace=git_ws,
        mode=JobMode.READ_ONLY,
    )
    assert ok
    assert err is None


def test_edit_mode_non_git_rejection(temp_workspace_env, monkeypatch):
    """Edit mode on non-git workspace must be refused unless allow_non_git is true."""
    monkeypatch.setattr(config, "agents_enabled", True)
    monkeypatch.setattr(config, "agents_panic", False)
    monkeypatch.setattr(config, "allowed_agent_user_ids", [12345])
    monkeypatch.setattr("app.agents.policy.is_agent_installed", lambda a: True)
    set_panic(False)

    workspaces = load_workspaces(temp_workspace_env["cfg_file"])
    local_ws = workspaces["local_plain"]

    # Non-git workspace with allow_non_git=False -> Edit mode rejected
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.CLINE,
        workspace=local_ws,
        mode=JobMode.EDIT,
    )
    assert not ok
    assert "not a git repository" in err

    # Read-only mode on non-git workspace is fine
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.CLINE,
        workspace=local_ws,
        mode=JobMode.READ_ONLY,
    )
    assert ok


def test_autonomous_gating(temp_workspace_env, monkeypatch):
    """Autonomous flags are blocked when autonomous_ok=False."""
    monkeypatch.setattr(config, "agents_enabled", True)
    monkeypatch.setattr(config, "agents_panic", False)
    monkeypatch.setattr(config, "allowed_agent_user_ids", [12345])
    monkeypatch.setattr("app.agents.policy.is_agent_installed", lambda a: True)
    set_panic(False)

    workspaces = load_workspaces(temp_workspace_env["cfg_file"])
    local_ws = workspaces["local_plain"]
    git_ws = workspaces["git_ws"]

    # local_plain has autonomous_ok=False
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.CLINE,
        workspace=local_ws,
        mode=JobMode.READ_ONLY,
        autonomous=True,
    )
    assert not ok
    assert "autonomous_ok=false" in err

    # git_ws has autonomous_ok=True
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.CLINE,
        workspace=git_ws,
        mode=JobMode.EDIT,
        autonomous=True,
    )
    assert ok


def test_panic_switch_and_authorization(temp_workspace_env, monkeypatch):
    """Panic switch and unauthorized senders immediately block operations."""
    monkeypatch.setattr(config, "agents_enabled", True)
    monkeypatch.setattr(config, "allowed_agent_user_ids", [12345])
    monkeypatch.setattr("app.agents.policy.is_agent_installed", lambda a: True)

    workspaces = load_workspaces(temp_workspace_env["cfg_file"])
    git_ws = workspaces["git_ws"]

    # Unauthorized sender
    ok, err = validate_dispatch_policy(
        sender_id="99999",
        agent=AgentKind.CLINE,
        workspace=git_ws,
        mode=JobMode.READ_ONLY,
    )
    assert not ok
    assert "not authorized" in err

    # Active panic switch
    set_panic(True)
    assert is_panic_active()
    ok, err = validate_dispatch_policy(
        sender_id="12345",
        agent=AgentKind.CLINE,
        workspace=git_ws,
        mode=JobMode.READ_ONLY,
    )
    assert not ok
    assert "panic" in err
    set_panic(False)
