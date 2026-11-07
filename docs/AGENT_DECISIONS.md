# Karna Agent Delegation: Architectural Decisions & Choices

This document logs all architectural decisions made during the design and implementation of Karna's Agent Delegation subsystem (integrating Cline CLI and Google Antigravity CLI via Telegram).

---

## Decision 1: Zero-LLM Confirmation and Slash Execution
- **Choice**: Dispatching confirmation cards, executing status/jobs queries, mode toggles, job cancellations (`/stop`), and emergency panic stops (`/panic`) run with zero LLM calls.
- **Rationale**: Preserves Karna's core invariant: deterministic operations must execute in under 50ms with 100% reliability. Routing dangerous system operations through an LLM introduces hallucination risk, latency, and prompt injection vectors.

## Decision 2: Subprocess Execution without Shell (`shell=False`)
- **Choice**: Every agent invocation and git subprocess strictly uses `asyncio.create_subprocess_exec` with an explicit argument list, setting `shell=False`.
- **Rationale**: Eliminates shell injection vulnerabilities entirely. Task descriptions, workspace paths, and commit hashes cannot trigger arbitrary shell commands or operators (`|`, `&`, `;`, `$()`).

## Decision 3: Process Group Isolation and Dual Timeout Supervision
- **Choice**: Child processes are launched in isolated process groups (`start_new_session=True`). Process supervision enforces both a total wall-clock timeout (`timeout_seconds`, default 600s) and an idle output timeout (`idle_timeout_seconds`, default 90s). On cancellation, panic, or timeout, termination sends `SIGTERM` to the entire group (`os.killpg(pgid, signal.SIGTERM)`), followed by a 5-second grace period before `SIGKILL`.
- **Rationale**: External coding CLIs spawn language servers, compilers, build runners, and subshells. Standard process killing leaves background daemons orphaned. Group signals clean up all children deterministically.

## Decision 4: Environment Variable Stripping & Secret Scrubbing
- **Choice**: Subprocesses receive an isolated, stripped environment (`build_isolated_env`) containing only minimal system variables (`PATH`, `HOME`, `LANG`, etc.). All sensitive application tokens (`TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, API keys) are wiped. In addition, all streaming output and generated logs pass through `strip_ansi` and `redact_secrets` before being displayed or saved.
- **Rationale**: External tools and scripts must never inherit Karna's credentials, database secrets, or bot tokens. Redacting output prevents accidental secret leakage back into chat or log files.

## Decision 5: PTY Execution for Antigravity and Streaming JSON for Cline
- **Choice**: Cline is executed in headless mode with `--json` streaming where supported. Antigravity requires a pseudo-terminal (PTY) to execute interactively via `pty.openpty()`, with flags preceding the `-p "<prompt>"` argument.
- **Rationale**: Antigravity is optimized for terminal sessions; running without a PTY causes buffer deadlocks and missed prompts. Cline provides structured JSON events that can be streamed for live status updates.

## Decision 6: Workspace Canonical Path Traversal and Symlink Containment
- **Choice**: Workspace paths in `config/agent_workspaces.yml` are resolved to real paths using `Path.resolve()`. Relative path traversal (`..`), non-existent directories, and symlink targets pointing outside the designated tree are rejected upfront.
- **Rationale**: Confines agent operations strictly to explicitly approved directory trees, preventing unintended access to host filesystems.

## Decision 7: Offline-First Cloud Gating (`cloud_ok` Policy)
- **Choice**: Workspaces must explicitly configure `cloud_ok: true` to permit Antigravity execution. Antigravity requests against workspaces with `cloud_ok: false` or omitted are rejected with a clear explanation before any confirmation card is produced.
- **Rationale**: Antigravity leverages Google Cloud models and tools. Workspaces containing proprietary, air-gapped, or sensitive local data must not inadvertently send context to cloud endpoints.

## Decision 8: Git Safety Net (Snapshots, Revert Instructions, and Diffs)
- **Choice**: For `edit` mode jobs in git workspaces, a temporary snapshot branch/tag (`karna-agent-snapshot-<id>`) is created before the agent runs. After completion, `git diff --stat` is captured, and clear revert commands (`git checkout <snapshot_ref>`) are provided in the Telegram completion report. Non-git workspaces reject `edit` mode unless `allow_non_git: true` is explicitly configured.
- **Rationale**: Allows the repository owner to review all automated code changes at a glance and revert immediately if the agent makes erroneous edits.

## Decision 9: Telegram 64-Byte Callback Data Budget & Atomic Nonce Verification
- **Choice**: Inline button callback data uses the compact format `agent:<act>:<short_id>:<nonce>` (e.g. `agent:run:a1b2c3d4:e5f6g7h8`), occupying under 40 bytes (well under Telegram's 64-byte limit). Confirmations are stored in SQLite and consumed atomically with a single-use nonce.
- **Rationale**: Prevents replay attacks, accidental double-clicks, and Telegram API callback payload errors.

## Decision 10: Automatic Crash Recovery for Orphaned Jobs on Startup
- **Choice**: During application startup and via periodic scheduler reap, any jobs remaining in `running` or `queued` state without an active process are transitioned to `interrupted` or `failed` with diagnostic error messages.
- **Rationale**: Ensures system consistency across restarts or unexpected crashes without leaving dangling orphaned job entries in the database.

## Decision 11: Constrained Fallback Dispatching with Strict Invariants
- **Choice**: Natural language requests that don't match deterministic regex patterns are routed through a strictly constrained LLM parser that outputs a single JSON object with `agent`, `workspace`, and `task`. If the LLM produces invalid JSON or unknown workspaces, it safely defaults to returning a clarification prompt instead of executing.
- **Rationale**: Allows conversational convenience while ensuring the execution path remains strictly guarded by policy validation and zero-LLM confirmation before any tool runs.
