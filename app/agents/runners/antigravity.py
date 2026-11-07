"""Antigravity CLI (agy) runner implementation with PTY output capture and cloud enforcement."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from typing import Any, Dict, List, Optional, Tuple

from app.agents.models import AgentJob, JobMode
from app.agents.runner_base import run_supervised_process
from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.agents.runners.antigravity")


class AntigravityRunner:
    """Invokes and parses output from Google Antigravity CLI (agy)."""

    def build_command(self, job: AgentJob, binary_path: str) -> List[str]:
        """Construct the argument list for agy.
        
        CRITICAL RULE: All flags must come BEFORE -p "<task>".
        """
        cmd: List[str] = [binary_path]

        # Workspace directory
        if job.workspace_path:
            cmd.extend(["--add-dir", job.workspace_path])

        # Mode selection
        if job.mode == JobMode.READ_ONLY:
            cmd.extend(["--mode", "plan"])
        elif job.mode == JobMode.EDIT:
            cmd.extend(["--mode", "accept-edits"])
            if job.autonomous:
                cmd.append("--dangerously-skip-permissions")

        # Resume conversation if provided
        if job.conversation_id:
            cmd.extend(["--conversation", job.conversation_id])

        # Extra flags configured in settings
        if config.agy_extra_args:
            extra = shlex.split(config.agy_extra_args)
            cmd.extend(extra)

        # Single prompt argument (-p) must be the final option
        cmd.extend(["-p", job.task_text])
        return cmd

    def parse_output(self, raw_output: str) -> Tuple[str, Optional[str]]:
        """Parse Antigravity output, extract meaningful response lines and summary."""
        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines) if lines else raw_output

        summary: Optional[str] = None
        if lines:
            # Use last 3 lines as preview summary
            summary = "\n".join(lines[-3:])

        return cleaned_text, summary

    def capabilities(self) -> Dict[str, Any]:
        """Return supported capabilities of the Antigravity runner."""
        return {
            "name": "antigravity",
            "supports_pty": True,
            "supports_conversation": True,
            "supports_modes": True,
            "cloud_backed": True,
        }

    async def startup_self_test(self, binary_path: Optional[str] = None) -> Tuple[bool, str]:
        """Verify that PTY-based process execution and output capture works properly."""
        from app.agents.policy import resolve_binary
        bin_path = binary_path or resolve_binary(AgentJob.from_row({"id": "1", "sender_id": "1", "agent": "antigravity", "workspace_alias": "", "workspace_path": "", "mode": "read_only", "autonomous": 0, "task_text": "", "status": "queued"}))
        if not bin_path:
            return False, "Antigravity CLI (agy) executable not found on PATH."

        log_path = os.path.join("data", "agent_jobs", "selftest.log")
        try:
            rc, out, timed_out, _ = await run_supervised_process(
                cmd=[bin_path, "--version"],
                cwd="/tmp",
                output_log_path=log_path,
                total_timeout_s=5,
                idle_timeout_s=3,
                use_pty=True,
            )
            if rc == 0 and out.strip():
                return True, f"PTY capture operational (version: {out.strip()})"
            return False, f"PTY test exited with code {rc}, output: {out[:100]}"
        except Exception as e:
            return False, f"PTY test failed with error: {e}"
