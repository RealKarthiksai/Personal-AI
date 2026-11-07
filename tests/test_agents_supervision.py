"""Tests for process supervision, environment isolation, redaction, and timeouts."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

from app.agents.redactor import clean_agent_output, redact_secrets, strip_ansi
from app.agents.runner_base import build_isolated_env, run_supervised_process

FAKE_CLINE = str(Path(__file__).parent / "fakes" / "fake_cline.py")
FAKE_AGY = str(Path(__file__).parent / "fakes" / "fake_agy.py")


def test_ansi_stripping_and_secret_redaction():
    """Verify ANSI escape stripping and credential scrubbing."""
    raw = "\x1b[31mError\x1b[0m: Authorization: Bearer sk-ant-api03-testkey1234567890abcdef\n"
    cleaned = clean_agent_output(raw)
    assert "\x1b[31m" not in cleaned
    assert "sk-ant-api03" not in cleaned
    assert "[REDACTED_AUTH_TOKEN]" in cleaned

    token_line = "TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ\n"
    redacted_token = redact_secrets(token_line)
    assert "123456789:ABC" not in redacted_token
    assert "[REDACTED_CREDENTIAL]" in redacted_token


def test_environment_isolation(monkeypatch):
    """Verify that Karna secrets in os.environ are completely stripped from agent env."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///sensitive.db")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = build_isolated_env(allowlist=["PATH", "USER"])
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert "PATH" in env


@pytest.mark.asyncio
async def test_supervised_process_success():
    """Test clean execution and output capture of fake cline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "stdout.log")
        rc, out, timed_out, was_idle = await run_supervised_process(
            cmd=[sys.executable, FAKE_CLINE, "--json", "test task"],
            cwd=tmpdir,
            output_log_path=out_file,
            total_timeout_s=10,
            idle_timeout_s=5,
        )
        assert rc == 0
        assert timed_out is False
        assert "Completed task successfully" in out
        assert os.path.isfile(out_file)


@pytest.mark.asyncio
async def test_supervised_process_secret_scrubbing():
    """Test that secrets emitted on stdout are scrubbed before writing to log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "stdout.log")
        rc, out, timed_out, was_idle = await run_supervised_process(
            cmd=[sys.executable, FAKE_CLINE, "--secret"],
            cwd=tmpdir,
            output_log_path=out_file,
            total_timeout_s=10,
            idle_timeout_s=5,
        )
        assert rc == 0
        assert "sk-ant-api03" not in out
        assert "[REDACTED_AUTH_TOKEN]" in out
        assert "987654321:ABC" not in out
        assert "[REDACTED_CREDENTIAL]" in out


@pytest.mark.asyncio
async def test_supervised_process_max_output_truncation():
    """Test that exceeding max_output_bytes stops execution and appends truncation marker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "stdout.log")
        rc, out, timed_out, was_idle = await run_supervised_process(
            cmd=[sys.executable, FAKE_CLINE, "--long-output"],
            cwd=tmpdir,
            output_log_path=out_file,
            total_timeout_s=10,
            idle_timeout_s=5,
            max_output_bytes=5000,  # 5 KB limit for test
        )
        assert "[TRUNCATED: Output exceeded maximum allowed size]" in out
        assert len(out) < 20000


@pytest.mark.asyncio
async def test_supervised_process_idle_timeout():
    """Test that a silent hanging process is terminated via idle timeout."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "stdout.log")
        rc, out, timed_out, was_idle = await run_supervised_process(
            cmd=[sys.executable, FAKE_CLINE, "--hang"],
            cwd=tmpdir,
            output_log_path=out_file,
            total_timeout_s=10,
            idle_timeout_s=1,  # 1 second idle timeout
        )
        assert timed_out is True
        assert was_idle is True
