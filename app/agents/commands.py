"""Direct slash command handlers for the Agent Delegation subsystem (0 LLM calls)."""

from __future__ import annotations

import html
import os
import shutil
from typing import Optional

from app.agents.confirmations import create_confirmation, render_confirmation_card
from app.agents.jobs import get_job_manager
from app.agents.models import AgentJob, AgentKind, DispatchRequest, JobMode, JobStatus
from app.agents.policy import (
    get_workspace,
    is_agent_installed,
    is_panic_active,
    load_workspaces,
    resolve_binary,
    validate_dispatch_policy,
)
from app.agents.runners.antigravity import AntigravityRunner
from app.config import config
from app.utils.logging import get_logger

if False:  # TYPE_CHECKING
    from app.services.tool_router import ToolExecutionResult

logger = get_logger("app.agents.commands")


def _get_router_types():
    from app.services.tool_router import ResponseMode, ToolExecutionResult
    return ResponseMode, ToolExecutionResult


def handle_workspaces_command() -> "ToolExecutionResult":
    """List all allowlisted workspaces with their flags (/workspaces)."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    workspaces = load_workspaces()
    if not workspaces:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct="<b>No workspaces configured.</b> Check <code>config/agent_workspaces.yml</code>.",
        )

    lines = ["📂 <b>Allowlisted Workspaces</b>\n"]
    for ws in workspaces.values():
        cloud_badge = "🌐 Cloud allowed" if ws.cloud_ok else "🔒 Local only"
        auto_badge = "⚡ Autonomous ok" if ws.autonomous_ok else "🛡️ Guarded"
        git_badge = "Plain folder ok" if ws.allow_non_git else "Git required"
        lines.append(
            f"• <b>{html.escape(ws.alias)}</b>\n"
            f"  Path: <code>{html.escape(ws.path)}</code>\n"
            f"  Policy: {cloud_badge} | {auto_badge} | {git_badge}\n"
        )

    return ToolExecutionResult(mode=ResponseMode.DIRECT, direct="\n".join(lines))


def handle_agent_status_command() -> "ToolExecutionResult":
    """Report CLI installation versions, PTY self-test status, and running jobs (/agent status)."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    cline_path = resolve_binary(AgentKind.CLINE)
    agy_path = resolve_binary(AgentKind.ANTIGRAVITY)

    cline_status = f"✅ Installed (<code>{cline_path}</code>)" if cline_path else "❌ Not found"
    agy_status = f"✅ Installed (<code>{agy_path}</code>)" if agy_path else "❌ Not found"

    lines = [
        "🤖 <b>Agent Delegation Status</b>\n",
        f"<b>Module Enabled:</b> {'✅ Yes' if config.agents_enabled else '❌ No (AGENTS_ENABLED=false)'}",
        f"<b>Panic Switch:</b> {'🚨 ACTIVE (All operations blocked)' if is_panic_active() else '🟢 Normal'}",
        f"<b>Cline CLI:</b> {cline_status}",
        f"<b>Antigravity CLI:</b> {agy_status}",
    ]

    # Active running jobs
    mgr = get_job_manager()
    jobs = mgr.list_jobs(limit=5)
    running = [j for j in jobs if j.status == JobStatus.RUNNING]
    queued = [j for j in jobs if j.status == JobStatus.QUEUED]

    lines.append(f"\n<b>Active Jobs:</b> {len(running)} running, {len(queued)} queued")
    for j in running:
        lines.append(f"• <code>{j.id[:8]}</code> ({j.agent.value} in {j.workspace_alias}): <i>{html.escape(j.task_text[:60])}</i>")

    return ToolExecutionResult(mode=ResponseMode.DIRECT, direct="\n".join(lines))


def handle_jobs_command(sender_id: Optional[str] = None) -> "ToolExecutionResult":
    """List recent agent jobs with their status and execution details (/jobs)."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    mgr = get_job_manager()
    jobs = mgr.list_jobs(sender_id=sender_id, limit=6)

    if not jobs:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct="<b>No agent jobs found.</b> To delegate a task, use <code>/agent &lt;cline|agy&gt; &lt;workspace&gt; &lt;task&gt;</code>.",
        )

    lines = ["📋 <b>Recent Agent Jobs</b>\n"]
    for j in jobs:
        short_id = j.id[:8]
        status_icons = {
            JobStatus.SUCCEEDED: "✅",
            JobStatus.FAILED: "❌",
            JobStatus.TIMED_OUT: "⏱️",
            JobStatus.CANCELLED: "⚠️",
            JobStatus.RUNNING: "🔄",
            JobStatus.QUEUED: "⏳",
            JobStatus.PENDING_CONFIRM: "❓",
            JobStatus.INTERRUPTED: "💥",
            JobStatus.REJECTED: "🚫",
        }
        icon = status_icons.get(j.status, "•")
        task_snippet = html.escape(j.task_text[:50])
        lines.append(
            f"{icon} <b><code>{short_id}</code></b> [{j.status.value}] ({j.agent.value} @ {j.workspace_alias})\n"
            f"   <i>\"{task_snippet}\"</i>\n"
            f"   Inspect: <code>/job {short_id}</code>\n"
        )

    return ToolExecutionResult(mode=ResponseMode.DIRECT, direct="\n".join(lines))


def handle_job_detail_command(job_id_or_prefix: str) -> "ToolExecutionResult":
    """Show details of a specific job (/job <id>)."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    mgr = get_job_manager()
    job = mgr.get_job(job_id_or_prefix)
    if not job:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct=f"❌ Job <code>{html.escape(job_id_or_prefix)}</code> not found.",
        )

    from app.agents.reporter import format_job_card
    card = format_job_card(job)
    return ToolExecutionResult(mode=ResponseMode.DIRECT, direct=card)


async def handle_stop_command(args: str, sender_id: str) -> "ToolExecutionResult":
    """Cancel a running or queued job (/stop [id])."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    target = args.strip()
    mgr = get_job_manager()

    if not target:
        # Stop most recent active job
        jobs = mgr.list_jobs(sender_id=sender_id, limit=5)
        active = [j for j in jobs if j.status in (JobStatus.RUNNING, JobStatus.QUEUED)]
        if not active:
            return ToolExecutionResult(mode=ResponseMode.DIRECT, direct="No active jobs to stop.")
        target = active[0].id

    ok, msg = await mgr.cancel_job(target, sender_id=sender_id)
    return ToolExecutionResult(mode=ResponseMode.DIRECT, direct=f"{'✅' if ok else '❌'} {msg}")


async def handle_panic_command(sender_id: str) -> "ToolExecutionResult":
    """Emergency kill switch (/panic): immediately terminate all running jobs."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    mgr = get_job_manager()
    count = await mgr.panic_stop_all(sender_id=sender_id)
    return ToolExecutionResult(
        mode=ResponseMode.DIRECT,
        direct=(
            f"🚨 <b>PANIC SWITCH ACTIVATED</b>\n\n"
            f"• Terminated <b>{count}</b> active agent processes.\n"
            f"• All future agent dispatches are strictly locked.\n"
            f"• To reset, restart the server with <code>AGENTS_PANIC=false</code>."
        ),
    )


def handle_resume_command(args: str, sender_id: str) -> "ToolExecutionResult":
    """Resume a previous Antigravity conversation as a new job (/resume <id> <message>)."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct="Usage: <code>/resume &lt;job_id&gt; &lt;follow_up_message&gt;</code>",
        )

    prev_id, follow_up_task = parts
    mgr = get_job_manager()
    prev_job = mgr.get_job(prev_id)
    if not prev_job:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct=f"❌ Previous job <code>{html.escape(prev_id)}</code> not found.",
        )

    if prev_job.agent != AgentKind.ANTIGRAVITY:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct="Conversation resumption is currently supported for Antigravity (agy) jobs.",
        )

    req = DispatchRequest(
        agent=AgentKind.ANTIGRAVITY,
        workspace_alias=prev_job.workspace_alias,
        task_text=follow_up_task,
        mode=prev_job.mode,
        autonomous=prev_job.autonomous,
        conversation_id=prev_job.id,  # Use previous job as conversation continuity token
    )

    from app.agents.router import dispatch_agent_request
    return dispatch_agent_request(req, sender_id=sender_id)
