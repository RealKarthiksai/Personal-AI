"""Confirmation store and inline keyboard callback handling for agent delegation."""

from __future__ import annotations

import html
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from app.agents.models import AgentJob, AgentKind, ConfirmationRecord, JobMode, JobStatus, WorkspaceConfig
from app.config import config
from app.database.database import transaction
from app.utils.logging import get_logger

logger = get_logger("app.agents.confirmations")


def record_audit_event(
    sender_id: str,
    event: str,
    job_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Append a security event to the agent_audit log table."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    details_json = json.dumps(details or {}, ensure_ascii=False)
    query = """
        INSERT INTO agent_audit (ts, sender_id, event, job_id, details)
        VALUES (?, ?, ?, ?, ?)
    """
    params = (now_str, str(sender_id), event, job_id, details_json)
    try:
        if conn is not None:
            conn.execute(query, params)
        else:
            with transaction() as c:
                c.execute(query, params)
    except Exception as e:
        logger.error("Failed to write to agent_audit: %s", e)


def create_confirmation(
    job: AgentJob,
    ttl_seconds: Optional[int] = None,
) -> Tuple[ConfirmationRecord, str]:
    """Store an agent job in pending_confirm and generate an atomic confirmation record.
    
    Returns (ConfirmationRecord, short_id).
    """
    ttl = ttl_seconds if ttl_seconds is not None else config.agent_confirm_ttl_s
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=ttl)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    conf_id = str(uuid.uuid4())
    nonce = secrets.token_hex(4)  # 8 characters
    short_id = job.id[:8]

    with transaction() as conn:
        # Insert job record if not already present, or update to pending_confirm
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_jobs (
                id, sender_id, channel, agent, workspace_alias, workspace_path,
                mode, autonomous, task_text, status, conversation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.sender_id,
                job.channel,
                job.agent.value,
                job.workspace_alias,
                job.workspace_path,
                job.mode.value,
                1 if job.autonomous else 0,
                job.task_text,
                JobStatus.PENDING_CONFIRM.value,
                job.conversation_id,
                job.created_at or now_str,
            ),
        )

        # Insert confirmation record
        conn.execute(
            """
            INSERT INTO agent_confirmations (id, job_id, sender_id, nonce, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conf_id, job.id, str(job.sender_id), nonce, expires_at),
        )

    record = ConfirmationRecord(
        id=conf_id,
        job_id=job.id,
        sender_id=str(job.sender_id),
        nonce=nonce,
        expires_at=expires_at,
    )

    record_audit_event(
        sender_id=job.sender_id,
        event="requested",
        job_id=job.id,
        details={
            "agent": job.agent.value,
            "workspace": job.workspace_alias,
            "mode": job.mode.value,
            "autonomous": job.autonomous,
            "expires_at": expires_at,
        },
    )

    return record, short_id


def render_confirmation_card(
    job: AgentJob,
    workspace: WorkspaceConfig,
    nonce: str,
) -> Tuple[str, dict]:
    """Render an HTML confirmation card and Telegram inline keyboard.
    
    Callback data format: agent:<action>:<short_id>:<nonce>
    Total callback_data length is ~30 chars, well below Telegram's 64-byte limit.
    """
    short_id = job.id[:8]
    agent_name = "Cline" if job.agent == AgentKind.CLINE else "Antigravity"
    badge = "🌐 Cloud" if job.agent == AgentKind.ANTIGRAVITY else "🔒 Local"
    mode_text = "can edit" if job.mode == JobMode.EDIT else "read-only"

    if job.mode == JobMode.EDIT:
        safety = "Git snapshot will be created before running"
        if job.autonomous:
            safety += " | ⚠️ <b>Autonomous flag enabled</b>"
    else:
        safety = "Plan/read-only mode; files will not be modified"

    escaped_task = html.escape(job.task_text)
    escaped_path = html.escape(workspace.path)
    escaped_alias = html.escape(workspace.alias)

    text = (
        f"⚡ <b>Agent Task Dispatch</b>\n\n"
        f"<b>Agent:</b> {agent_name}  |  <b>Mode:</b> {mode_text}  |  <b>{badge}</b>\n"
        f"<b>Workspace:</b> <code>{escaped_alias}</code> (<code>{escaped_path}</code>)\n"
        f"<b>Task:</b> <i>\"{escaped_task}\"</i>\n"
        f"<b>Safety:</b> {safety}\n\n"
        f"<i>Please confirm execution below (expires in {config.agent_confirm_ttl_s // 60}m):</i>"
    )

    toggle_target = "Edit" if job.mode == JobMode.READ_ONLY else "Read-only"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": f"agent:conf:{short_id}:{nonce}"},
                {"text": "❌ Cancel", "callback_data": f"agent:canc:{short_id}:{nonce}"},
            ],
            [
                {"text": f"Switch to {toggle_target}", "callback_data": f"agent:mode:{short_id}:{nonce}"}
            ],
        ]
    }

    return text, keyboard


def consume_confirmation(
    short_id: str,
    nonce: str,
    clicking_user_id: str,
    action: str,
) -> Tuple[bool, Optional[AgentJob], str]:
    """Process a button tap on a confirmation card within an atomic transaction.
    
    Actions:
      - 'conf': Confirm job, transition to queued
      - 'canc': Cancel job, transition to cancelled
      - 'mode': Toggle mode between read_only and edit
      
    Returns (success, updated_job, status_message).
    """
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    with transaction() as conn:
        # Lookup confirmation row by job short prefix and nonce
        row = conn.execute(
            """
            SELECT c.id as conf_id, c.job_id, c.sender_id, c.nonce, c.expires_at, c.used_at,
                   j.id, j.channel, j.agent, j.workspace_alias, j.workspace_path,
                   j.mode, j.autonomous, j.task_text, j.status, j.conversation_id, j.created_at
            FROM agent_confirmations c
            JOIN agent_jobs j ON c.job_id = j.id
            WHERE j.id LIKE ? || '%' AND c.nonce = ?
            ORDER BY c.expires_at DESC LIMIT 1
            """,
            (short_id, nonce),
        ).fetchone()

        if not row:
            record_audit_event(clicking_user_id, "policy-denied", details={"reason": "invalid_nonce_or_id"}, conn=conn)
            return False, None, "Invalid or unrecognized confirmation request."

        # Verify authorized clicking user
        if str(clicking_user_id) != str(row["sender_id"]):
            record_audit_event(
                clicking_user_id,
                "policy-denied",
                job_id=row["job_id"],
                details={"reason": "user_mismatch", "expected": row["sender_id"]},
                conn=conn,
            )
            return False, None, "Only the user who initiated this request may confirm it."

        # Check if already used
        if row["used_at"] and action != "mode":
            return False, None, "This confirmation has already been used."

        # Check expiry
        expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if now_utc > expires_at:
            conn.execute(
                "UPDATE agent_jobs SET status = ? WHERE id = ?",
                (JobStatus.REJECTED.value, row["job_id"]),
            )
            record_audit_event(clicking_user_id, "policy-denied", job_id=row["job_id"], details={"reason": "expired"}, conn=conn)
            return False, None, "This confirmation request has expired."

        job = AgentJob.from_row(row)

        if action == "canc":
            conn.execute("UPDATE agent_confirmations SET used_at = ? WHERE id = ?", (now_str, row["conf_id"]))
            conn.execute(
                "UPDATE agent_jobs SET status = ?, finished_at = ? WHERE id = ?",
                (JobStatus.CANCELLED.value, now_str, job.id),
            )
            job.status = JobStatus.CANCELLED
            job.finished_at = now_str
            record_audit_event(clicking_user_id, "rejected", job_id=job.id, details={"action": "cancel"}, conn=conn)
            return True, job, "Job was cancelled."

        elif action == "mode":
            new_mode = JobMode.EDIT if job.mode == JobMode.READ_ONLY else JobMode.READ_ONLY
            conn.execute("UPDATE agent_jobs SET mode = ? WHERE id = ?", (new_mode.value, job.id))
            job.mode = new_mode
            record_audit_event(clicking_user_id, "mode_toggle", job_id=job.id, details={"new_mode": new_mode.value}, conn=conn)
            return True, job, f"Mode switched to {new_mode.value}."

        elif action == "conf":
            conn.execute("UPDATE agent_confirmations SET used_at = ? WHERE id = ?", (now_str, row["conf_id"]))
            conn.execute(
                "UPDATE agent_jobs SET status = ?, confirmed_at = ? WHERE id = ?",
                (JobStatus.QUEUED.value, now_str, job.id),
            )
            job.status = JobStatus.QUEUED
            job.confirmed_at = now_str
            record_audit_event(clicking_user_id, "confirmed", job_id=job.id, conn=conn)
            return True, job, "Job confirmed and queued for execution."

        return False, None, f"Unknown action: {action}"
