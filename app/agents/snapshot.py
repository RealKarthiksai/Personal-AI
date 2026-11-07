"""Git safety net: snapshot checkpoint creation, diff statistics, and revert instructions."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, Tuple

from app.utils.logging import get_logger

logger = get_logger("app.agents.snapshot")


async def _run_git_cmd(cwd: str, *args: str) -> Tuple[int, str, str]:
    """Execute a git command safely without shell=True."""
    cmd = ["git", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )
    except Exception as e:
        logger.error("Failed to run git command %s in %s: %s", cmd, cwd, e)
        return -1, "", str(e)


async def create_snapshot(workspace_path: str, job_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Create a git snapshot checkpoint before an edit-mode job runs.
    
    Records current HEAD SHA and creates a recovery branch karna/job-<short_id>.
    Returns (success, head_sha, branch_name).
    """
    canonical = os.path.realpath(workspace_path)
    git_dir = os.path.join(canonical, ".git")
    if not os.path.isdir(git_dir):
        logger.warning("create_snapshot: %s is not a git repository", canonical)
        return False, None, None

    # 1. Get current HEAD commit SHA
    rc, head_sha, err = await _run_git_cmd(canonical, "rev-parse", "HEAD")
    if rc != 0 or not head_sha:
        logger.error("Failed to resolve git HEAD in %s: %s", canonical, err)
        return False, None, None

    # 2. Create a reference checkpoint branch
    short_id = job_id[:8]
    branch_name = f"karna/job-{short_id}"
    rc, _, err = await _run_git_cmd(canonical, "branch", "-f", branch_name, head_sha)
    if rc != 0:
        logger.warning("Could not create checkpoint branch %s: %s", branch_name, err)
        # Still return head_sha even if branch creation fails
        return True, head_sha, None

    logger.info("Created git snapshot checkpoint in %s: head=%s, branch=%s", canonical, head_sha[:8], branch_name)
    return True, head_sha, branch_name


async def get_diff_stat(workspace_path: str, snapshot_ref: str) -> str:
    """Compute git diff --stat against the pre-job snapshot reference."""
    canonical = os.path.realpath(workspace_path)
    rc, out, _ = await _run_git_cmd(canonical, "diff", "--stat", snapshot_ref)
    if rc == 0 and out:
        return out
    # Also check unstaged changes if working tree was modified
    rc2, out2, _ = await _run_git_cmd(canonical, "diff", "--stat")
    if rc2 == 0 and out2:
        return out2
    return "No changes detected."


def format_revert_instructions(workspace_path: str, snapshot_ref: str, branch: Optional[str] = None) -> str:
    """Format clear, safe git commands allowing the user to inspect or revert agent edits."""
    ref = branch or snapshot_ref[:8]
    return (
        f"To review or revert these changes in <code>{os.path.basename(workspace_path)}</code>:\n"
        f"• Review full diff: <code>git diff {ref}</code>\n"
        f"• Revert all working tree edits: <code>git restore . && git clean -fd</code>\n"
        f"• Restore to snapshot commit: <code>git reset --hard {ref}</code>"
    )
