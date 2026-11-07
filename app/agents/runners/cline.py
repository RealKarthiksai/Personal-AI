"""Cline CLI runner implementation supporting JSON event stream and plan mode."""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List, Optional, Tuple

from app.agents.models import AgentJob, JobMode
from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.agents.runners.cline")


class ClineRunner:
    """Invokes and parses output from Cline CLI (npm i -g cline)."""

    def build_command(self, job: AgentJob, binary_path: str) -> List[str]:
        """Construct the argument list for Cline CLI without shell=True."""
        cmd: List[str] = [binary_path]

        # Mode selection
        if job.mode == JobMode.READ_ONLY:
            cmd.append("-p")  # Plan mode
        elif job.mode == JobMode.EDIT and job.autonomous:
            cmd.extend(["--auto-approve", "true"])

        # Enable structured JSON output
        cmd.append("--json")

        # Workspace directory
        if job.workspace_path:
            cmd.extend(["-c", job.workspace_path])

        # Extra flags configured in settings
        if config.cline_extra_args:
            extra = shlex.split(config.cline_extra_args)
            cmd.extend(extra)

        # Single prompt argument
        cmd.append(job.task_text)
        return cmd

    def parse_output(self, raw_output: str) -> Tuple[str, Optional[str]]:
        """Parse Cline output: parse JSON stream lines or fallback to plain text."""
        lines = raw_output.splitlines()
        extracted_texts: List[str] = []
        last_summary: Optional[str] = None

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    content = data.get("content") or data.get("message") or data.get("text")
                    if content:
                        extracted_texts.append(str(content))
                    if data.get("type") in ("result", "summary", "done"):
                        last_summary = str(content)
                    continue
                except Exception:
                    pass
            extracted_texts.append(line_str)

        cleaned_text = "\n".join(extracted_texts) if extracted_texts else raw_output
        if not last_summary and extracted_texts:
            # Use the last 3 non-empty lines as summary preview
            last_summary = "\n".join(extracted_texts[-3:])

        return cleaned_text, last_summary

    def capabilities(self) -> Dict[str, Any]:
        """Return supported capabilities of the Cline runner."""
        return {
            "name": "cline",
            "supports_plan_mode": True,
            "supports_json": True,
            "supports_autonomous": True,
            "headless": True,
        }
