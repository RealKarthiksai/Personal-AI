"""Domain models and data structures for the Agent Delegation subsystem."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentKind(str, Enum):
    """Supported external coding/ops agent CLIs."""
    CLINE = "cline"
    ANTIGRAVITY = "antigravity"

    @classmethod
    def _missing_(cls, value: object) -> Optional[AgentKind]:
        if isinstance(value, str):
            val_clean = value.strip().lower()
            val_clean = re.sub(r"\s*(?:2(?:\.0)?|v\d+)\b", "", val_clean).strip()
            if val_clean in ("agy", "antigravity", "antigravty"):
                return cls.ANTIGRAVITY
            if val_clean in ("cline", "clline", "clien"):
                return cls.CLINE
        return None


class JobStatus(str, Enum):
    """Lifecycle states for an agent delegation job."""
    PENDING_CONFIRM = "pending_confirm"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    REJECTED = "rejected"


class JobMode(str, Enum):
    """Execution permission mode for an agent job."""
    READ_ONLY = "read_only"
    EDIT = "edit"


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configured workspace folder with security permissions."""
    alias: str
    path: str
    cloud_ok: bool = False
    autonomous_ok: bool = False
    allow_non_git: bool = False


@dataclass
class AgentJob:
    """Represents an agent delegation job and its state."""
    id: str
    sender_id: str
    channel: str = "telegram"
    agent: AgentKind = AgentKind.CLINE
    workspace_alias: str = ""
    workspace_path: str = ""
    mode: JobMode = JobMode.READ_ONLY
    autonomous: bool = False
    task_text: str = ""
    status: JobStatus = JobStatus.PENDING_CONFIRM
    pid: Optional[int] = None
    pgid: Optional[int] = None
    conversation_id: Optional[str] = None
    snapshot_ref: Optional[str] = None
    branch: Optional[str] = None
    exit_code: Optional[int] = None
    output_path: Optional[str] = None
    output_summary: Optional[str] = None
    diff_stat: Optional[str] = None
    created_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_row(cls, row: Any) -> AgentJob:
        """Hydrate an AgentJob instance from an SQLite sqlite3.Row or dict."""
        data = dict(row)
        return cls(
            id=data["id"],
            sender_id=data["sender_id"],
            channel=data.get("channel", "telegram"),
            agent=AgentKind(data["agent"]),
            workspace_alias=data["workspace_alias"],
            workspace_path=data["workspace_path"],
            mode=JobMode(data["mode"]),
            autonomous=bool(data.get("autonomous", 0)),
            task_text=data["task_text"],
            status=JobStatus(data["status"]),
            pid=data.get("pid"),
            pgid=data.get("pgid"),
            conversation_id=data.get("conversation_id"),
            snapshot_ref=data.get("snapshot_ref"),
            branch=data.get("branch"),
            exit_code=data.get("exit_code"),
            output_path=data.get("output_path"),
            output_summary=data.get("output_summary"),
            diff_stat=data.get("diff_stat"),
            created_at=data.get("created_at"),
            confirmed_at=data.get("confirmed_at"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class DispatchRequest:
    """Incoming user request parsed to delegate a task to an agent."""
    agent: AgentKind
    workspace_alias: Optional[str]
    task_text: str
    mode: JobMode = JobMode.READ_ONLY
    autonomous: bool = False
    conversation_id: Optional[str] = None


@dataclass(frozen=True)
class ConfirmationRecord:
    """Pending confirmation stored in SQLite with one-shot nonce."""
    id: str
    job_id: str
    sender_id: str
    nonce: str
    expires_at: str
    used_at: Optional[str] = None
    telegram_message_id: Optional[str] = None
