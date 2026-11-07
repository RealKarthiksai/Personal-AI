"""Security policy enforcement, workspace allowlist validation, and permission gating."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from app.agents.models import AgentKind, JobMode, WorkspaceConfig
from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.agents.policy")

_PANIC_ACTIVE: bool = False


class PolicyError(Exception):
    """Raised when an agent operation violates safety or workspace policy."""


def set_panic(active: bool = True) -> None:
    """Set the in-memory panic lock switch."""
    global _PANIC_ACTIVE
    _PANIC_ACTIVE = active
    logger.warning("Agent panic switch state changed: active=%s", active)


def is_panic_active() -> bool:
    """Return True if server config or in-memory switch has panic enabled."""
    return bool(_PANIC_ACTIVE or config.agents_panic)


def load_workspaces(config_path: Optional[str] = None) -> Dict[str, WorkspaceConfig]:
    """Load and validate the workspace allowlist from YAML or JSON.
    
    Resolves canonical realpaths, verifies directory existence, and ensures
    strict containment without symlink escapes.
    """
    path_str = config_path or config.agent_workspaces_file
    cfg_file = Path(path_str)
    if not cfg_file.is_file():
        logger.warning("Agent workspaces file not found at %s", path_str)
        return {}

    try:
        raw_text = cfg_file.read_text(encoding="utf-8")
        if cfg_file.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(raw_text) or {}
        else:
            data = json.loads(raw_text)
    except Exception as e:
        logger.error("Failed to parse agent workspaces file %s: %s", path_str, e)
        return {}

    workspaces: Dict[str, WorkspaceConfig] = {}
    items = data.get("workspaces", [])
    if isinstance(items, list):
        for item in items:
            alias = str(item.get("alias", "")).strip().lower()
            raw_path = str(item.get("path", "")).strip()
            if not alias or not raw_path:
                continue

            # Resolve realpath to neutralize symlink traversal and relative '..' components
            try:
                canonical = os.path.realpath(os.path.expanduser(raw_path))
            except Exception:
                continue

            # Must exist and be a directory
            if not os.path.isdir(canonical):
                logger.warning("Workspace directory does not exist or is not a dir: %s (%s)", alias, canonical)
                continue

            # Reject root or home directory as allowable workspaces
            if canonical in ("/", os.path.realpath(os.path.expanduser("~"))):
                logger.warning("Refusing root or user home directory as workspace: %s", canonical)
                continue

            ws = WorkspaceConfig(
                alias=alias,
                path=canonical,
                cloud_ok=bool(item.get("cloud_ok", False)),
                autonomous_ok=bool(item.get("autonomous_ok", False)),
                allow_non_git=bool(item.get("allow_non_git", False)),
            )
            workspaces[alias] = ws

    return workspaces


def get_workspace(alias: str, config_path: Optional[str] = None) -> Optional[WorkspaceConfig]:
    """Retrieve an allowlisted workspace by case-insensitive alias."""
    workspaces = load_workspaces(config_path)
    return workspaces.get(alias.strip().lower())


def validate_workspace_path(path: str, config_path: Optional[str] = None) -> Optional[WorkspaceConfig]:
    """Ensure a filesystem path is contained within an allowlisted workspace."""
    canonical = os.path.realpath(os.path.expanduser(path))
    workspaces = load_workspaces(config_path)
    for ws in workspaces.values():
        try:
            # Check if canonical path is identical to or subpath of ws.path
            common = os.path.commonpath([canonical, ws.path])
            if common == ws.path:
                return ws
        except ValueError:
            # Different drives on Windows
            continue
    return None


def resolve_binary(agent: AgentKind) -> Optional[str]:
    """Locate the executable path for the requested agent CLI."""
    if agent == AgentKind.CLINE:
        explicit = config.cline_bin
        if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        return shutil.which("cline")
    elif agent == AgentKind.ANTIGRAVITY:
        explicit = config.agy_bin
        if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        return shutil.which("agy")
    return None


def is_agent_installed(agent: AgentKind) -> bool:
    """Return True if the requested agent executable is available."""
    return resolve_binary(agent) is not None


def is_git_repository(path: str) -> bool:
    """Check if the given directory contains a git repository."""
    canonical = os.path.realpath(path)
    git_dir = os.path.join(canonical, ".git")
    return os.path.exists(git_dir)


def validate_dispatch_policy(
    sender_id: str,
    agent: AgentKind,
    workspace: WorkspaceConfig,
    mode: JobMode,
    autonomous: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Validate all security policies for dispatching an agent job.
    
    Returns (True, None) on success or (False, error_reason) on failure.
    """
    if is_panic_active():
        return False, "Agent subsystem is disabled due to active panic switch."

    if not config.agents_enabled:
        return False, "Agent delegation is disabled in server configuration (AGENTS_ENABLED=false)."

    # Verify sender authorization
    try:
        sender_int = int(sender_id)
        if sender_int not in config.allowed_agent_user_ids:
            return False, f"Sender {sender_id} is not authorized for agent operations."
    except ValueError:
        return False, f"Invalid sender ID: {sender_id}"

    # Verify agent executable exists
    if not is_agent_installed(agent):
        return False, f"Agent CLI '{agent.value}' is not installed or not found on PATH."

    # Verify Antigravity cloud policy
    if agent == AgentKind.ANTIGRAVITY and not workspace.cloud_ok:
        return (
            False,
            f"Workspace '{workspace.alias}' has cloud_ok=false. "
            "Antigravity is cloud-backed and cannot be used on local-only workspaces."
        )

    # Verify edit mode on non-git workspace
    if mode == JobMode.EDIT and not is_git_repository(workspace.path) and not workspace.allow_non_git:
        return (
            False,
            f"Workspace '{workspace.alias}' is not a git repository and allow_non_git is false. "
            "Edit mode is disabled to protect against unrecoverable changes."
        )

    # Autonomous flag gating
    if autonomous and not workspace.autonomous_ok:
        return (
            False,
            f"Autonomous execution is disabled on workspace '{workspace.alias}' (autonomous_ok=false)."
        )

    return True, None
