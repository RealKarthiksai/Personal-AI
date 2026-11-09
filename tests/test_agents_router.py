"""Tests for agent router: deterministic parsing, constrained-LLM fallback, and zero-LLM confirmation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from app.agents.models import AgentKind, JobMode
from app.agents.router import (
    dispatch_agent_request,
    parse_deterministic_request,
    resolve_ambiguous_routing_with_llm,
)
from app.config import config
from app.database import database
from app.services.llm_client import LLMClient
from app.services.tool_router import ResponseMode


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up isolated test database and workspace configuration."""
    with tempfile.NamedTemporaryFile(suffix=".db") as db_f, tempfile.TemporaryDirectory() as tmpdir:
        db_path = db_f.name
        monkeypatch.setattr(database.config, "database_url", f"sqlite:///{db_path}")
        database._init_lock = False
        database.init_db()

        # Create sample workspace
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

        yield {"ws_dir": ws_dir, "cfg_file": str(cfg_file)}


def test_deterministic_slash_agent_parsing():
    """Verify explicit slash command parsing."""
    req = parse_deterministic_request("/agent cline karna run the test suite and fix failures")
    assert req is not None
    assert req.agent == AgentKind.CLINE
    assert req.workspace_alias == "karna"
    assert "run the test suite and fix failures" in req.task_text
    assert req.mode == JobMode.EDIT  # "fix" triggered edit mode

    req_ro = parse_deterministic_request("/agent agy karna analyze repository structure")
    assert req_ro is not None
    assert req_ro.agent == AgentKind.ANTIGRAVITY
    assert req_ro.workspace_alias == "karna"
    assert req_ro.mode == JobMode.READ_ONLY


def test_deterministic_natural_language_parsing():
    """Verify natural language patterns."""
    # "ask cline to run tests"
    req1 = parse_deterministic_request("ask cline to run tests in karna")
    assert req1 is not None
    assert req1.agent == AgentKind.CLINE
    assert req1.workspace_alias == "karna"

    # "use antigravity to refactor the scheduler"
    req2 = parse_deterministic_request("use antigravity to refactor the scheduler in karna")
    assert req2 is not None
    assert req2.agent == AgentKind.ANTIGRAVITY
    assert req2.mode == JobMode.EDIT

    # "with cline: check types"
    req3 = parse_deterministic_request("with cline: check types")
    assert req3 is not None
    assert req3.agent == AgentKind.CLINE
    assert "check types" in req3.task_text

    # "but u can send messages to antigravity and clline i want you to give me or return my coding foldder structure for mee"
    req4 = parse_deterministic_request(
        "but u can send messages to antigravity and clline i want you to give me or return my coding foldder structure for mee"
    )
    assert req4 is not None
    assert req4.agent in (AgentKind.ANTIGRAVITY, AgentKind.CLINE)
    assert "give me or return my coding foldder structure for mee" in req4.task_text
    assert req4.mode == JobMode.READ_ONLY


def test_dispatch_agent_request_zero_llm():
    """Assert dispatching an agent task produces ResponseMode.ACTION with 0 LLM calls."""
    req = parse_deterministic_request("ask cline to fix tests in karna")
    assert req is not None

    res = dispatch_agent_request(req, sender_id="12345")
    assert res.mode == ResponseMode.ACTION
    assert res.action_card is not None
    assert res.action_keyboard is not None
    assert "⚡ <b>Agent Task Dispatch</b>" in res.action_card
    assert res.action_job is not None


@pytest.mark.asyncio
async def test_constrained_llm_fallback(monkeypatch):
    """Test LLM fallback when natural language is ambiguous."""
    mock_llm = AsyncMock(spec=LLMClient)
    mock_llm.generate.return_value = json.dumps({"agent": "cline", "workspace": "karna"})

    result = await resolve_ambiguous_routing_with_llm("Can someone inspect the tests?", llm_client=mock_llm)
    assert result is not None
    agent, ws = result
    assert agent == AgentKind.CLINE
    assert ws == "karna"
    assert mock_llm.generate.await_count == 1


def test_direct_address_and_antigravity_2_parsing():
    """Verify direct address and Antigravity 2.0 / smart quote parsing."""
    user_msg = (
        "Antigravity 2.0, here’s what I need you to do:\n"
        "1. Extract the frontend code from /home/vhanghar/Karna/ (HTML, CSS, JS).\n"
        "2. Run it in your browser or deploy to"
    )
    req = parse_deterministic_request(user_msg)
    assert req is not None
    assert req.agent == AgentKind.ANTIGRAVITY
    assert req.workspace_alias == "karna"
    assert "Extract the frontend code" in req.task_text

    # Slash command with version suffix
    req_slash = parse_deterministic_request("/agent agy 2.0 karna run build")
    assert req_slash is not None
    assert req_slash.agent == AgentKind.ANTIGRAVITY
    assert req_slash.workspace_alias == "karna"
    assert "run build" in req_slash.task_text


@pytest.mark.asyncio
async def test_tool_router_agent_delegation_action_mode():
    """Verify tool_router.route_and_execute returns ResponseMode.ACTION for agent delegation."""
    from app.services.tool_router import tool_router

    user_msg = (
        "Antigravity 2.0, here’s what I need you to do: run frontend in karna"
    )
    res = await tool_router.route_and_execute(user_msg, sender_id="12345")
    assert res.mode == ResponseMode.ACTION
    assert res.action_card is not None
    assert "Agent Task Dispatch" in res.action_card
    assert res.action_keyboard is not None


def test_policy_denial_formatting(monkeypatch):
    """Verify that policy denial formats correctly without crashing on html.escape."""
    monkeypatch.setattr(config, "agents_enabled", False)
    req = parse_deterministic_request("/agent agy stop running the website")
    assert req is not None
    res = dispatch_agent_request(req, sender_id="12345")
    assert res.mode == ResponseMode.DIRECT
    assert "Policy Denial" in res.direct
    assert "AGENTS_ENABLED=false" in res.direct

