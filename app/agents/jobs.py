"""Job lifecycle manager: creation, execution supervision, cancellation, and crash recovery."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.agents.confirmations import record_audit_event
from app.agents.models import AgentJob, AgentKind, DispatchRequest, JobMode, JobStatus, WorkspaceConfig
from app.agents.policy import get_workspace, is_panic_active, resolve_binary, set_panic
from app.agents.runner_base import run_supervised_process, terminate_process_group
from app.agents.snapshot import create_snapshot, format_revert_instructions, get_diff_stat
from app.config import config
from app.database.database import get_connection, transaction
from app.utils.logging import get_logger

logger = get_logger("app.agents.jobs")


class JobManager:
    """Coordinates lifecycle, execution, and state persistence of delegated agent jobs."""

    def __init__(self) -> None:
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def create_job(
        self,
        request: DispatchRequest,
        sender_id: str,
        channel: str = "telegram",
    ) -> AgentJob:
        """Create a new AgentJob in pending_confirm state and persist to database."""
        job_id = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        ws = get_workspace(request.workspace_alias or "")
        ws_path = ws.path if ws else ""
        ws_alias = ws.alias if ws else (request.workspace_alias or "")

        job = AgentJob(
            id=job_id,
            sender_id=str(sender_id),
            channel=channel,
            agent=request.agent,
            workspace_alias=ws_alias,
            workspace_path=ws_path,
            mode=request.mode,
            autonomous=request.autonomous,
            task_text=request.task_text,
            status=JobStatus.PENDING_CONFIRM,
            conversation_id=request.conversation_id,
            created_at=now_str,
        )

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO agent_jobs (
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
                    job.status.value,
                    job.conversation_id,
                    job.created_at,
                ),
            )

        return job

    def get_job(self, job_id_or_prefix: str) -> Optional[AgentJob]:
        """Fetch an AgentJob by full UUID or short prefix."""
        with transaction() as conn:
            row = conn.execute(
                """
                SELECT id, sender_id, channel, agent, workspace_alias, workspace_path,
                       mode, autonomous, task_text, status, pid, pgid, conversation_id,
                       snapshot_ref, branch, exit_code, output_path, output_summary,
                       diff_stat, created_at, confirmed_at, started_at, finished_at, error
                FROM agent_jobs
                WHERE id = ? OR id LIKE ? || '%'
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_id_or_prefix, job_id_or_prefix),
            ).fetchone()

            if row:
                return AgentJob.from_row(row)
        return None

    def list_jobs(self, sender_id: Optional[str] = None, limit: int = 5) -> List[AgentJob]:
        """List recent agent jobs, optionally filtered by sender."""
        with transaction() as conn:
            if sender_id is not None:
                rows = conn.execute(
                    """
                    SELECT id, sender_id, channel, agent, workspace_alias, workspace_path,
                           mode, autonomous, task_text, status, pid, pgid, conversation_id,
                           snapshot_ref, branch, exit_code, output_path, output_summary,
                           diff_stat, created_at, confirmed_at, started_at, finished_at, error
                    FROM agent_jobs
                    WHERE sender_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (str(sender_id), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, sender_id, channel, agent, workspace_alias, workspace_path,
                           mode, autonomous, task_text, status, pid, pgid, conversation_id,
                           snapshot_ref, branch, exit_code, output_path, output_summary,
                           diff_stat, created_at, confirmed_at, started_at, finished_at, error
                    FROM agent_jobs
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

            return [AgentJob.from_row(r) for r in rows]

    async def cancel_job(self, job_id_or_prefix: str, sender_id: str) -> Tuple[bool, str]:
        """Cancel an active or queued job, terminating the process group if running."""
        job = self.get_job(job_id_or_prefix)
        if not job:
            return False, f"Job '{job_id_or_prefix}' not found."

        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMED_OUT):
            return False, f"Job {job.id[:8]} has already completed with status: {job.status.value}"

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if job.pgid and job.status == JobStatus.RUNNING:
            terminate_process_group(job.pgid)

        task = self._running_jobs.get(job.id)
        if task and not task.done():
            task.cancel()

        with transaction() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = ?, finished_at = ? WHERE id = ?",
                (JobStatus.CANCELLED.value, now_str, job.id),
            )

        record_audit_event(sender_id, "stopped", job_id=job.id, details={"cancelled_by": sender_id})
        return True, f"Job {job.id[:8]} was cancelled."

    def recover_interrupted_jobs(self) -> List[str]:
        """Crash recovery routine called on startup to mark orphaned jobs as interrupted."""
        recovered: List[str] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT id, sender_id, pgid, status FROM agent_jobs
                WHERE status IN ('running', 'queued')
                """
            ).fetchall()

            for r in rows:
                job_id = r["id"]
                pgid = r["pgid"]
                if pgid:
                    terminate_process_group(pgid)

                conn.execute(
                    """
                    UPDATE agent_jobs
                    SET status = ?, finished_at = ?, error = ?
                    WHERE id = ?
                    """,
                    (JobStatus.INTERRUPTED.value, now_str, "Server restarted while job was active", job_id),
                )
                recovered.append(job_id)
                record_audit_event("system", "interrupted", job_id=job_id, details={"recovered_on_startup": True}, conn=conn)

        if recovered:
            logger.warning("Agent crash recovery: Marked %d orphaned jobs as interrupted", len(recovered))
        return recovered

    async def panic_stop_all(self, sender_id: str) -> int:
        """Emergency kill switch: terminates all active agent processes and activates panic lock."""
        set_panic(True)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        count = 0

        with transaction() as conn:
            rows = conn.execute(
                "SELECT id, sender_id, pgid FROM agent_jobs WHERE status = 'running'"
            ).fetchall()

            for r in rows:
                count += 1
                job_id = r["id"]
                pgid = r["pgid"]
                if pgid:
                    terminate_process_group(pgid)
                conn.execute(
                    """
                    UPDATE agent_jobs
                    SET status = ?, finished_at = ?, error = ?
                    WHERE id = ?
                    """,
                    (JobStatus.CANCELLED.value, now_str, "Panic switch activated", job_id),
                )
                record_audit_event(sender_id, "panic", job_id=job_id, details={"action": "emergency_stop"}, conn=conn)

        for task in self._running_jobs.values():
            if not task.done():
                task.cancel()
        self._running_jobs.clear()

        record_audit_event(sender_id, "panic", details={"stopped_jobs_count": count})
        logger.critical("PANIC SWITCH ACTIVATED: Stopped %d running jobs.", count)
        return count

    async def dispatch_queued_job(self, job_id: str) -> None:
        """Background runner task to execute a confirmed queued job."""
        task = asyncio.create_task(self._run_job_lifecycle(job_id))
        self._running_jobs[job_id] = task

    async def _run_job_lifecycle(self, job_id: str) -> None:
        """Execute full job lifecycle with git checkpoint, runner execution, and reporting."""
        async with self._lock:
            job = self.get_job(job_id)
            if not job or job.status != JobStatus.QUEUED:
                return

            if is_panic_active():
                with transaction() as conn:
                    conn.execute(
                        "UPDATE agent_jobs SET status = ?, error = ? WHERE id = ?",
                        (JobStatus.REJECTED.value, "Panic switch active", job.id),
                    )
                return

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            log_dir = os.path.join("data", "agent_jobs", job.id)
            os.makedirs(log_dir, exist_ok=True)
            output_log_path = os.path.join(log_dir, "stdout.log")

            # 1. Update status to RUNNING
            with transaction() as conn:
                conn.execute(
                    "UPDATE agent_jobs SET status = ?, started_at = ?, output_path = ? WHERE id = ?",
                    (JobStatus.RUNNING.value, now_str, output_log_path, job.id),
                )
            record_audit_event(job.sender_id, "started", job_id=job.id)

            # 2. Git Snapshot for edit mode
            snapshot_ref: Optional[str] = None
            branch_name: Optional[str] = None
            if job.mode == JobMode.EDIT and job.workspace_path:
                ok, snapshot_ref, branch_name = await create_snapshot(job.workspace_path, job.id)
                if ok and snapshot_ref:
                    with transaction() as conn:
                        conn.execute(
                            "UPDATE agent_jobs SET snapshot_ref = ?, branch = ? WHERE id = ?",
                            (snapshot_ref, branch_name, job.id),
                        )

            # 3. Resolve Runner and Command
            bin_path = resolve_binary(job.agent)
            if not bin_path:
                err_msg = f"Binary for agent '{job.agent.value}' not found."
                self._mark_finished(job.id, JobStatus.FAILED, -1, err_msg)
                return

            from app.agents.runners.cline import ClineRunner
            from app.agents.runners.antigravity import AntigravityRunner

            runner = ClineRunner() if job.agent == AgentKind.CLINE else AntigravityRunner()
            cmd = runner.build_command(job, bin_path)
            use_pty = (job.agent == AgentKind.ANTIGRAVITY)

            def _record_pid(pid: int, pgid: int) -> None:
                with transaction() as conn:
                    conn.execute("UPDATE agent_jobs SET pid = ?, pgid = ? WHERE id = ?", (pid, pgid, job.id))

            # 4. Supervised Process Execution
            exit_code, full_output, timed_out, was_idle = await run_supervised_process(
                cmd=cmd,
                cwd=job.workspace_path or os.getcwd(),
                output_log_path=output_log_path,
                use_pty=use_pty,
                on_pid=_record_pid,
            )

            # 5. Diff Stat for edit mode
            diff_stat: Optional[str] = None
            if job.mode == JobMode.EDIT and snapshot_ref and job.workspace_path:
                diff_stat = await get_diff_stat(job.workspace_path, snapshot_ref)

            # 6. Parse Output & Determine Status
            cleaned_text, summary = runner.parse_output(full_output)

            if timed_out:
                final_status = JobStatus.TIMED_OUT
                err = "Job timed out (idle timeout)" if was_idle else "Job timed out (total execution limit)"
            elif exit_code == 0:
                final_status = JobStatus.SUCCEEDED
                err = None
            else:
                final_status = JobStatus.FAILED
                err = f"Agent exited with code {exit_code}"

            self._mark_finished(
                job.id,
                final_status,
                exit_code,
                error=err,
                output_summary=summary or cleaned_text[:300],
                diff_stat=diff_stat,
            )

            # 7. Deliver result notification to Telegram
            try:
                from app.agents.reporter import deliver_job_result
                refreshed_job = self.get_job(job.id)
                if refreshed_job:
                    await deliver_job_result(refreshed_job)
            except Exception as e:
                logger.error("Failed to deliver job result to Telegram: %s", e)

            self._running_jobs.pop(job.id, None)

    def _mark_finished(
        self,
        job_id: str,
        status: JobStatus,
        exit_code: int,
        error: Optional[str] = None,
        output_summary: Optional[str] = None,
        diff_stat: Optional[str] = None,
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with transaction() as conn:
            conn.execute(
                """
                UPDATE agent_jobs
                SET status = ?, exit_code = ?, error = ?, output_summary = ?, diff_stat = ?, finished_at = ?
                WHERE id = ?
                """,
                (status.value, exit_code, error, output_summary, diff_stat, now_str, job_id),
            )
        job = self.get_job(job_id)
        if job:
            record_audit_event(
                job.sender_id,
                "finished",
                job_id=job.id,
                details={"status": status.value, "exit_code": exit_code, "error": error},
            )


_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    """Return the singleton JobManager instance."""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
