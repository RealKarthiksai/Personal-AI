"""Base protocol and process supervision for agent runners."""

from __future__ import annotations

import asyncio
import os
import pty
import signal
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Tuple

from app.agents.models import AgentJob
from app.agents.redactor import clean_agent_output
from app.config import config
from app.utils.logging import get_logger

logger = get_logger("app.agents.runner_base")


class AgentRunner(Protocol):
    """Protocol implemented by agent CLI runners (Cline, Antigravity)."""

    def build_command(self, job: AgentJob, binary_path: str) -> List[str]:
        """Construct the argument list to launch the agent CLI without shell=True."""
        ...

    def parse_output(self, raw_output: str) -> Tuple[str, Optional[str]]:
        """Parse stdout/stderr to extract cleaned text and an optional structured summary."""
        ...

    def capabilities(self) -> Dict[str, Any]:
        """Return the detected capabilities and supported flags of the CLI."""
        ...


def build_isolated_env(
    allowlist: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build a sanitized environment mapping containing only allowlisted keys.
    
    Prevents Karna secrets (such as TELEGRAM_BOT_TOKEN) from being inherited by child agent processes.
    """
    allowed_keys = allowlist
    if allowed_keys is None:
        raw = config.agent_env_allowlist or ""
        allowed_keys = [k.strip() for k in raw.split(",") if k.strip()]

    clean_env: Dict[str, str] = {}
    for key in allowed_keys:
        val = os.environ.get(key)
        if val is not None:
            clean_env[key] = val

    if extra_env:
        for k, v in extra_env.items():
            clean_env[k] = v

    return clean_env


def terminate_process_group(pgid: int, grace_period_s: float = 3.0) -> None:
    """Terminate an entire process group safely: SIGTERM first, then SIGKILL escalation."""
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as e:
        logger.warning("Error sending SIGTERM to process group %d: %s", pgid, e)

    # Allow grace period then escalate to SIGKILL if still running
    try:
        # Check if process group is still alive
        os.killpg(pgid, 0)
        # If it didn't raise ProcessLookupError, it's alive; kill it
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.warning("Error escalating to SIGKILL on process group %d: %s", pgid, e)


async def run_supervised_process(
    cmd: List[str],
    cwd: str,
    output_log_path: str,
    total_timeout_s: Optional[int] = None,
    idle_timeout_s: Optional[int] = None,
    max_output_bytes: Optional[int] = None,
    use_pty: bool = False,
    allowlist: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
    on_pid: Optional[Callable[[int, int], None]] = None,
    on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Tuple[int, str, bool, bool]:
    """Execute an agent command with process group isolation, output streaming, and dual timeouts.
    
    Returns (exit_code, full_output, timed_out, was_idle_timeout).
    """
    total_timeout = total_timeout_s if total_timeout_s is not None else config.agent_job_timeout_s
    idle_timeout = idle_timeout_s if idle_timeout_s is not None else config.agent_idle_timeout_s
    max_bytes = max_output_bytes if max_output_bytes is not None else config.agent_output_max_bytes

    env = build_isolated_env(allowlist=allowlist, extra_env=extra_env)
    os.makedirs(os.path.dirname(output_log_path), exist_ok=True)

    master_fd: Optional[int] = None
    slave_fd: Optional[int] = None

    if use_pty:
        try:
            master_fd, slave_fd = pty.openpty()
        except Exception as e:
            logger.warning("Failed to openpty(); falling back to standard pipe: %s", e)
            master_fd, slave_fd = None, None

    stdout_dest = slave_fd if slave_fd is not None else asyncio.subprocess.PIPE
    stderr_dest = slave_fd if slave_fd is not None else asyncio.subprocess.STDOUT

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=stdout_dest,
            stderr=stderr_dest,
            start_new_session=True,  # Creates a new process group/session
        )
    finally:
        if slave_fd is not None:
            os.close(slave_fd)

    pid = proc.pid
    pgid = os.getpgid(pid) if pid else 0
    if on_pid and pid:
        on_pid(pid, pgid)

    captured_chunks: List[str] = []
    total_bytes = 0
    truncated = False
    timed_out = False
    was_idle_timeout = False

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    last_output_time = loop.time()

    async def read_stream_pipe() -> None:
        nonlocal total_bytes, last_output_time, truncated
        if proc.stdout is None:
            return
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            cleaned = clean_agent_output(text)
            captured_chunks.append(cleaned)
            total_bytes += len(cleaned.encode("utf-8"))
            last_output_time = loop.time()

            if total_bytes >= max_bytes:
                truncated = True
                captured_chunks.append("\n[TRUNCATED: Output exceeded maximum allowed size]\n")
                terminate_process_group(pgid)
                break

    async def read_stream_pty() -> None:
        nonlocal total_bytes, last_output_time, truncated
        if master_fd is None:
            return
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, os.fdopen(master_fd, "rb", buffering=0))
        while True:
            try:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                cleaned = clean_agent_output(text)
                captured_chunks.append(cleaned)
                total_bytes += len(cleaned.encode("utf-8"))
                last_output_time = loop.time()

                if total_bytes >= max_bytes:
                    truncated = True
                    captured_chunks.append("\n[TRUNCATED: Output exceeded maximum allowed size]\n")
                    terminate_process_group(pgid)
                    break
            except (OSError, EOFError):
                break

    read_task = asyncio.create_task(read_stream_pty() if master_fd is not None else read_stream_pipe())

    # Watchdog loop supervising timeouts
    while proc.returncode is None:
        now = loop.time()
        # Check total timeout
        if (now - start_time) > total_timeout:
            timed_out = True
            was_idle_timeout = False
            terminate_process_group(pgid)
            break
        # Check idle timeout
        if (now - last_output_time) > idle_timeout:
            timed_out = True
            was_idle_timeout = True
            terminate_process_group(pgid)
            break
        await asyncio.sleep(0.5)

    try:
        await asyncio.wait_for(read_task, timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        terminate_process_group(pgid)

    full_output = "".join(captured_chunks)

    # Persist log to file
    try:
        with open(output_log_path, "w", encoding="utf-8") as f:
            f.write(full_output)
    except Exception as e:
        logger.error("Failed to write agent output log %s: %s", output_log_path, e)

    exit_code = proc.returncode if proc.returncode is not None else -1
    return exit_code, full_output, timed_out, was_idle_timeout
