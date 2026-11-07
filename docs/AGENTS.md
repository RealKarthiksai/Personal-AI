# Karna Agent Delegation Subsystem (Cline CLI & Antigravity CLI)

## 1. Overview & Architecture

Karna includes an **Agent Delegation Subsystem** that allows authorized repository owners, directly from Telegram chat, to delegate complex coding, refactoring, analysis, and ops tasks to two local CLI agents:

1. **Cline CLI (`cline`)**: Headless coding and operations agent.
2. **Antigravity CLI (`agy`)**: Google's agent CLI with multimodal and reasoning capabilities.

### Core Architectural Invariant
**Karna's local LLM (e.g. Qwen 3.5 2B) never touches the host system.**
The local LLM only assists with routing (deciding agent and workspace if natural phrasing is used). The actual execution is handled strictly by external CLI binaries inside isolated process groups, supervised by Karna's job manager with deterministic security gating and zero-LLM confirmation.

```
Telegram User ──> [Tool Router] ──> [Policy Check] ──> [Zero-LLM Confirmation Card]
                         │
                         ▼ (On Button Press: [Run / Toggle / Cancel])
                  [Job Manager]
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
    [Git Snapshot]               [Isolated Subprocess Group]
    (Safety Net)                 (build_isolated_env, PTY / JSON)
                                        │
                                        ▼
                                 [Cline / Antigravity]
                                        │
                                        ▼
                                 [Secret Redactor]
                                        │
                                        ▼
                                [Telegram Report]
                                (Summary, Diff, Revert)
```

---

## 2. Installation & CLI Prerequisites

### Cline CLI (`cline`)
Install Cline globally via npm:
```bash
npm install -g cline
# Verify installation
which cline
cline --version
```

### Antigravity CLI (`agy`)
Antigravity is installed as part of the Google Antigravity developer suite:
```bash
# Verify installation
which agy
agy --version
```

Ensure the binaries are reachable via `PATH` or configure explicit paths in your `.env`:
```env
CLINE_BIN=cline
AGY_BIN=agy
```

---

## 3. Configuration

### Workspace Allowlist (`config/agent_workspaces.yml`)
Agents are strictly confined to pre-registered workspaces. Any path not explicitly defined in `config/agent_workspaces.yml` is rejected upfront.

```yaml
workspaces:
  - alias: "karna"
    path: "/home/vhanghar/Karna"
    cloud_ok: true          # Set true to allow cloud-backed Antigravity
    autonomous_ok: false    # Require step-by-step confirmation if true
    allow_non_git: false    # Edit mode requires a git repository
```

#### Fields:
- `alias`: Short identifier used in commands (e.g. `/agent cline karna ...`).
- `path`: Absolute or user-relative path. Symlink escapes or path traversals (`..`) are rejected.
- `cloud_ok`: If `false`, Antigravity CLI is rejected to prevent accidental cloud data leakage from private/air-gapped repos.
- `autonomous_ok`: Whether fully autonomous execution without human-in-the-loop steps is permitted.
- `allow_non_git`: When `false`, `edit` mode requires an initialized Git repo to enable automatic snapshots.

### Environment Configuration (`.env`)
```env
# Enable or disable the delegation system globally
AGENTS_ENABLED=true

# Panic switch (set true to halt all agent invocations immediately)
AGENTS_PANIC=false

# Restrict agent commands to trusted Telegram IDs (comma-separated)
AGENTS_ALLOWED_USER_IDS=123456789

# Timeouts and limits
AGENT_TIMEOUT_SECONDS=600        # Max execution time (10 minutes)
AGENT_IDLE_TIMEOUT_SECONDS=90    # Max silence without stdout/stderr before kill
AGENT_MAX_OUTPUT_BYTES=524288    # 512 KB max log capture
```

---

## 4. Telegram Commands & Interaction

### Deterministic Commands (Zero-LLM, <50ms)

| Command | Description |
|---|---|
| `/agent <agent> <workspace> <task>` | Dispatch an agent task with inline confirmation card |
| `/agent status` | Show current active agent job and system panic state |
| `/workspaces` | List all configured workspaces, paths, and policies |
| `/jobs [limit]` | List recent agent jobs with status and execution time |
| `/job <id>` | View full details, logs path, git diff, and status of a job |
| `/stop [id]` | Stop the currently running job or a specific job ID |
| `/panic` | Emergency stop: kills all running jobs and blocks new jobs |
| `/resume` | Clear emergency panic state and resume operations |

### Natural Language Phrasing
Natural phrases are parsed deterministically or via constrained classification:
- `ask cline to run pytest in karna`
- `use antigravity in karna to refactor auth module`
- `with cline: fix formatting in tests`

---

## 5. Security & Safety Invariants

1. **Zero Direct Execution**: Subprocesses are spawned using `asyncio.create_subprocess_exec` (`shell=False`). No shell interpreters are used.
2. **Process Group Containment**: Processes run with `start_new_session=True`. Cancellation or timeout issues `SIGTERM` to the process group (`os.killpg`), followed by `SIGKILL` after a 5s grace period.
3. **Environment Isolation**: Subprocess environment is scrubbed (`build_isolated_env`). Karna's bot tokens, database URLs, and API keys are completely stripped.
4. **Secret Scrubbing**: Output text and logs pass through regex redactors that strip ANSI escape codes and redact Bearer tokens, private keys, API keys, and environment variables.
5. **Git Safety Net**: In `edit` mode, a temporary git snapshot branch (`karna-agent-snapshot-<id>`) is created prior to running. The completion report includes `git diff --stat` and explicit revert commands (`git checkout <snapshot_ref>`).
6. **Confirmation Verification**: Inline Telegram buttons use short 64-byte nonces stored in SQLite (`agent:<act>:<short_id>:<nonce>`). Replays, double-taps, or foreign user taps are rejected atomically.
7. **Crash Recovery**: Orphaned jobs in `running` or `queued` state at startup or during scheduler reaping are transitioned to `interrupted`.
8. **Append-Only Audit Log**: Every dispatch, confirmation, toggle, cancellation, and execution result is recorded in the `agent_audit` SQLite table.
