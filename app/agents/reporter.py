"""Telegram progress and completion reporter for delegated agent jobs."""

from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Optional

from app.agents.models import AgentJob, AgentKind, JobMode, JobStatus
from app.agents.snapshot import format_revert_instructions
from app.services.telegram_client import TelegramClient
from app.utils.logging import get_logger

logger = get_logger("app.agents.reporter")


def calculate_duration_str(started_at: Optional[str], finished_at: Optional[str]) -> str:
    """Compute human-friendly runtime duration between ISO timestamps."""
    if not started_at or not finished_at:
        return "< 1s"
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        secs = int((t1 - t0).total_seconds())
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        rem_secs = secs % 60
        return f"{mins}m {rem_secs}s"
    except Exception:
        return "N/A"


def format_job_card(job: AgentJob) -> str:
    """Format an informative HTML report card for Telegram delivery."""
    short_id = job.id[:8]
    agent_name = "Cline" if job.agent == AgentKind.CLINE else "Antigravity"
    duration = calculate_duration_str(job.started_at, job.finished_at)

    if job.status == JobStatus.SUCCEEDED:
        status_header = f"✅ <b>Agent Job Completed</b> (<code>{short_id}</code>)"
    elif job.status == JobStatus.TIMED_OUT:
        status_header = f"⏱️ <b>Agent Job Timed Out</b> (<code>{short_id}</code>)"
    elif job.status == JobStatus.CANCELLED:
        status_header = f"⚠️ <b>Agent Job Cancelled</b> (<code>{short_id}</code>)"
    else:
        status_header = f"❌ <b>Agent Job Failed</b> (<code>{short_id}</code>)"

    lines = [
        status_header,
        f"<b>Agent:</b> {agent_name}  |  <b>Workspace:</b> <code>{html.escape(job.workspace_alias)}</code>",
        f"<b>Duration:</b> {duration}  |  <b>Mode:</b> {job.mode.value}",
        f"<b>Task:</b> <i>\"{html.escape(job.task_text)}\"</i>",
    ]

    if job.error:
        lines.append(f"\n<b>Error:</b> <code>{html.escape(job.error)}</code>")

    if job.diff_stat and job.diff_stat != "No changes detected.":
        lines.append(f"\n<b>Files Changed:</b>\n<pre>{html.escape(job.diff_stat[:800])}</pre>")
        if job.snapshot_ref:
            lines.append(f"\n{format_revert_instructions(job.workspace_path, job.snapshot_ref, job.branch)}")

    if job.output_summary:
        summary_preview = html.escape(job.output_summary[:600])
        lines.append(f"\n<b>Output Summary:</b>\n<pre>{summary_preview}</pre>")

    if job.agent == AgentKind.ANTIGRAVITY:
        lines.append(f"\n<i>To follow up: <code>/resume {short_id} &lt;message&gt;</code></i>")

    return "\n".join(lines)


async def deliver_job_result(job: AgentJob, client: Optional[TelegramClient] = None) -> None:
    """Deliver completion notification and optional log document attachment to Telegram."""
    tg = client or TelegramClient()
    card_html = format_job_card(job)

    # Send status card
    await tg.send_text(chat_id=job.sender_id, text=card_html)

    # If log file exists and has substance (> 3000 bytes), send as attachment
    if job.output_path and os.path.isfile(job.output_path):
        size = os.path.getsize(job.output_path)
        if size > 3000:
            caption = f"Full execution log for job <code>{job.id[:8]}</code> ({size // 1024} KB)"
            await tg.send_document(chat_id=job.sender_id, document_path=job.output_path, caption=caption)
