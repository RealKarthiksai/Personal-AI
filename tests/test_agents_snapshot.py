"""Tests for git safety net: snapshot checkpointing, diff stats, and revert formatting."""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from app.agents.snapshot import create_snapshot, format_revert_instructions, get_diff_stat


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository with an initial commit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=str(repo_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "KarnaTest"], cwd=str(repo_path), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@karna.local"], cwd=str(repo_path), check=True, capture_output=True
        )

        test_file = repo_path / "app.py"
        test_file.write_text("print('version 1')\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=str(repo_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial commit"], cwd=str(repo_path), check=True, capture_output=True
        )

        yield repo_path


@pytest.mark.asyncio
async def test_create_snapshot_and_diff(temp_git_repo):
    """Test creating a snapshot and computing git diff after edits."""
    job_id = str(uuid.uuid4())
    ok, head_sha, branch_name = await create_snapshot(str(temp_git_repo), job_id)
    assert ok is True
    assert head_sha is not None
    assert branch_name == f"karna/job-{job_id[:8]}"

    # Make an edit to the repo
    file_path = temp_git_repo / "app.py"
    file_path.write_text("print('version 2 - modified by agent')\n", encoding="utf-8")

    # Add a new file
    new_file = temp_git_repo / "new_module.py"
    new_file.write_text("def hello(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "new_module.py"], cwd=str(temp_git_repo), check=True, capture_output=True)

    # Compute diff stat
    diff_stat = await get_diff_stat(str(temp_git_repo), head_sha)
    assert "app.py" in diff_stat or "new_module.py" in diff_stat

    # Revert instructions formatting
    revert_text = format_revert_instructions(str(temp_git_repo), head_sha, branch_name)
    assert branch_name in revert_text
    assert "git restore ." in revert_text
