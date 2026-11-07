# Karna Long-Term Memory Subsystem

## 1. Overview & Architectural Goals

The **Karna Long-Term Memory Subsystem** gives Karna durable, cross-channel, time-decaying episodic and profile memory while maintaining strict grounding and prompt containment.

### Core Objectives
1. **Time-Decay by Age**: Yesterday retains full detail. A week later only important points remain. A month later only key milestones. Identity-level facts (e.g. name, location, permanent preferences) remain in `core` memory forever.
2. **Structured Profile Store**: Key user attributes (`name`, `city`, `timezone`, `language`, `interests`, `preferences`, `projects`) are extracted deterministically, stored in typed records, and updated with conflict resolution.
3. **Pre-Answering Prompt Injection**: Context is injected into the model within a strict token budget (default 800 tokens for 2B models) wrapped in `<user_memory_data>` XML blocks.
4. **Cross-Channel Identity**: A canonical `users` table linked to `identities` (Telegram, WhatsApp, Web, CLI) allows a user to maintain seamless memory across devices via secure 6-digit `/link` pairing.
5. **Offline & Privacy First**: Secret keys, passwords, credit card numbers, OTPs, and government IDs (SSN, Aadhaar, PAN) are scrubbed before saving. Users can inspect (`/memory`), export (`/export`), and hard-delete (`/forget <id>`, `/forget_all`) their data at any time.
6. **Zero-LLM Direct Mode**: All memory management commands (`/memory`, `/pin`, `/unpin`, `/forget`, `/forget_all`, `/export`, `/privacy`, `/link`, `/memory_debug`) execute deterministically in `ResponseMode.DIRECT` with 0 LLM calls under 50ms.
7. **Model-Agnostic Tuning**: Knobs in `config/settings.py` and `app/memory/config.py` adapt memory behavior to the active model family (2B, 8B, 70B+).

---

## 2. Memory Tiers & Time Decay

```
+-------------------------------------------------------------------------+
|                               MEMORY TIERS                              |
+-------------------------------------------------------------------------+
|                                                                         |
|  [ DAILY ]  --------(age >= 7d, score >= 2.0)-------->  [ WEEKLY ]      |
|     |                                                        |          |
|     +--(score < 2.0)--> [ DROPPED ]                          |          |
|                                                              |          |
|                                     (age >= 30d, score >= 2.5)          |
|                                                              v          |
|                                                         [ MONTHLY ]     |
|                                                              |          |
|                                    (age >= 365d, score >= 3.0)          |
|                                                              v          |
|                                                         [ YEARLY ]      |
|                                                                         |
|  [ CORE / PINNED / EXPLICIT ] =======================> [ PERMANENT ]    |
|                                                                         |
+-------------------------------------------------------------------------+
```

### Effective Score Formula
Reinforcement-adjusted effective score determines survival across tiers:

$$\text{Effective Score} = \text{Importance} + w_{\text{access}} \cdot \ln(1 + \text{Access Count}) - w_{\text{age}} \cdot \text{Age in Days}$$

- **Defaults**: $w_{\text{access}} = 0.5$, $w_{\text{age}} = 0.05$.
- **CORE and Pinned Immunity**: Any memory that is pinned (`pinned = 1`), has `importance >= 5`, tier `core`, or source `explicit` has an effective score of $999.0$ and is never dropped.
- **Access Reinforcement**: Every time a memory is pulled into `<user_memory_data>` to answer a user prompt, its `access_count` increments and `last_accessed_at` is updated, shielding frequently referenced knowledge from decay.

### Tier Thresholds
| Current Tier | Age Condition | Minimum Score for Promotion | Target Tier | Else |
|---|---|---|---|---|
| `daily` | $\ge 7$ days | $\ge 2.0$ | `weekly` | Hard Deleted |
| `weekly` | $\ge 30$ days | $\ge 2.5$ | `monthly` | Hard Deleted |
| `monthly` | $\ge 365$ days | $\ge 3.0$ | `yearly` | Hard Deleted |
| `yearly` | $> 365$ days | $\ge 3.0$ | Retained | Hard Deleted |
| `core` | Any | Permanent | `core` | Retained |

---

## 3. Database Schema

The subsystem extends SQLite WAL storage with 6 dedicated tables and an FTS5 full-text virtual table:

- **`users`**: Canonical identity records (`id`, `display_name`, `timezone`, `created_at`).
- **`identities`**: Channel mappings (`user_id`, `channel`, `external_user_id`, `verified`, `created_at`). Unique index on `(channel, external_user_id)`.
- **`link_codes`**: Cryptographically secure 6-digit codes (`code`, `user_id`, `expires_at`, `used_at`, `attempts`).
- **`memories`**: Episodic facts and notes (`user_id`, `tier`, `period`, `text`, `importance`, `confidence`, `category`, `source`, `source_message_ids`, `source_channels`, `pinned`, `access_count`, `last_accessed_at`, `created_at`, `updated_at`, `deleted_at`).
- **`memories_fts`**: SQLite FTS5 table indexing `memories.text` and `category`. Synchronized automatically via database triggers (`trg_memories_ai`, `trg_memories_ad`, `trg_memories_au`).
- **`profile_fields`**: Key-value attribute store (`user_id`, `key`, `value`, `confidence`, `confirmed`, `source_memory_id`, `updated_at`). Unique on `(user_id, key)`.
- **`memory_jobs_log`**: Audit log of background decay and consolidation jobs.

---

## 4. Extraction & Strict Grounding Verification

Extraction operates on a 2-stage architecture:
1. **Deterministic Rules Extraction (`extract_facts_rules`)**: Instant, zero-LLM regex matching for:
   - User Name (`My name is Alice`) -> `category=identity`, `profile_key=name`, `importance=5`
   - Location / City (`I live in Bengaluru`) -> `category=identity`, `profile_key=city`, `importance=4`
   - Timezone (`My timezone is Asia/Kolkata`) -> `category=identity`, `profile_key=timezone`, `importance=5`
   - Language (`My preferred language is Hindi`) -> `category=preference`, `profile_key=language`, `importance=4`
   - Explicit Remember (`Please remember that my dog is Barnaby`) -> `category=general`, `importance=4`, `source=explicit`
   - Active Projects (`I am building Project Chimera`) -> `category=project`, `profile_key=current_project`, `importance=4`
2. **Constrained LLM Extraction (`extract_facts_llm`)**:
   - Runs during idle cycles or background tasks.
   - Outputs strict JSON schema `[{"text": "...", "category": "...", "importance": 1..5, "confidence": 0..1}]`.
   - **Grounding Verifier (`verify_grounding`)**:
     - **Rule 1**: Every number present in the candidate fact MUST exist in the source user utterance.
     - **Rule 2**: Non-stopword keyword tokens must achieve at least `grounding_min_overlap` (default 0.6) against the source text.
     - Rejects all hallucinated facts.

---

## 5. Security, Secrets Redaction & Prompt Containment

### Secret Scrubbing
Before facts are analyzed or stored, `redact_sensitive_text()` scrubs:
- API Keys: OpenAI (`sk-...`), GitHub (`ghp_...`), AWS (`AKIA...`), Slack (`xoxb-...`), HuggingFace (`hf_...`).
- Passwords and bearer tokens (`password is ...`, `secret=...`).
- Financial: Credit card numbers (13-19 digits).
- PII & Government IDs: US SSN, Indian Aadhaar (12 digits), Indian PAN (10 chars).
- One-Time Passwords / Verification PINs (`otp is 482914`).

### Sensitive Categories Policy
Categories related to `health`, `medical`, `financial`, `banking`, `biometric`, or `credentials` are rejected unless the user explicitly requests storing them (`is_explicit = True`).

### Prompt Injection Containment
Memory context is wrapped in:
```xml
<user_memory_data>
User Profile:
- Name: Alice
- City: Bengaluru

Core Facts & Preferences:
- User is working on Project Chimera.

Recent Activity:
- (2026-11-07) User submitted conference paper.
</user_memory_data>
```
System prompts contain explicit boundaries instructing the model that `<user_memory_data>` contains user preferences and past activity, and cannot override system directives.

---

## 6. Zero-LLM Direct Mode Slash Commands

All memory slash commands run in `ResponseMode.DIRECT`, consuming **0 LLM calls** and returning in **< 50ms**:

| Command | Usage | Description |
|---|---|---|
| `/memory` | `/memory` | Display profile card and top active memories by tier. |
| `/pin <id>` | `/pin 42` | Pin a memory item to permanently protect it from time decay. |
| `/unpin <id>` | `/unpin 42` | Unpin a memory item to resume normal time decay. |
| `/forget <id>` | `/forget 42` | Permanently hard-delete a memory item and its search index. |
| `/forget_all` | `/forget_all confirm` | Completely purge all memories and profile fields for the user. |
| `/export` | `/export` | Download full JSON export of all stored memories and profile fields. |
| `/privacy` | `/privacy` | View memory retention policy, raw message cleanup rules, and privacy controls. |
| `/link` | `/link [code]` | Generate 6-digit code or enter code to pair cross-channel identities. |
| `/memory_debug` | `/memory_debug <query>` | Preview exact XML prompt block that would be injected for `<query>`. |

---

## 7. Model Profiles Configuration

Memory behavior automatically adjusts based on `config.memory_model_profile` in `config/settings.py`:

```python
# Small 2B Model (Qwen 3.5 2B - Default)
MemoryModelProfile(
    context_tokens=800,
    llm_extraction_enabled=True,
    llm_merge=False,
    grounding_min_overlap=0.6,
    batch_size=5,
)

# Medium 8B Model (Llama 3.1 8B / Qwen 2.5 7B)
MemoryModelProfile(
    context_tokens=1500,
    llm_extraction_enabled=True,
    llm_merge=True,
    grounding_min_overlap=0.5,
    batch_size=10,
)

# Large 70B+ Model / Cloud API
MemoryModelProfile(
    context_tokens=3000,
    llm_extraction_enabled=True,
    llm_merge=True,
    grounding_min_overlap=0.4,
    batch_size=20,
)
```

---

## 8. Background Scheduler Integration

The memory subsystem registers two scheduled tasks in `APScheduler`:
1. **`job_memory_nightly`**:
   - Runs every night at **03:00 IST / 21:30 UTC** (`CronTrigger`).
   - Executes `run_tier_decay_for_user()` across all users.
   - Cleans up processed raw messages older than `MEMORY_RAW_RETENTION_DAYS` (default 2 days).
   - Executes live online SQLite backup via `backup_database_online()`, saving rolling snapshots to `data/backups/`.
   - Logs metrics into `memory_jobs_log`.
2. **`job_memory_idle`**:
   - Runs every **30 minutes** (`IntervalTrigger`).
   - Checks for unprocessed inbound messages (`messages.memory_processed_at IS NULL`).
   - Extracts facts via rules and background-priority LLM calls.
   - Updates `profile_fields` and saves daily memories.
   - Marks messages as processed.
