# Karna Long-Term Memory: Architectural Decisions & Choices

This document logs all architectural decisions made during the design and implementation of Karna's long-term, time-decaying, multi-channel memory subsystem.

---

## Decision 1: Model-Agnostic Settings Wrapper
- **Choice**: Configured all model-dependent knobs in `MemoryModelProfile` in `app/memory/config.py` backed by environment variables in `config/settings.py` and `app/config.py`.
- **Rationale**: When swapping the local Qwen 3.5 2B model for a larger local or remote model, budgets, grounding thresholds, and merge flags can be tuned by editing environment variables or config alone without touching code.

## Decision 2: Zero-LLM Direct Mode for Memory Commands
- **Choice**: Routed `/memory`, `/forget`, `/forget_all`, `/pin`, `/unpin`, `/export`, `/privacy`, `/link`, and `/memory_debug` through `ResponseMode.DIRECT`.
- **Rationale**: Preserves Karna's core invariant: operational queries must execute deterministically in under 50ms with zero LLM inference. Memory manipulation is programmatic and never subject to hallucination.

## Decision 3: Grounding Verification with Token Overlap
- **Choice**: Implemented deterministic entity and token overlap verification (`MEMORY_GROUNDING_MIN_OVERLAP=0.6`) between candidate facts and source message text.
- **Rationale**: The 2B model tends to pad or invent details during extraction. If key entities (names, numbers, dates, content tokens) do not match the source user text, the fact is rejected.

## Decision 4: Extractive Consolidation Default
- **Choice**: Default `MEMORY_LLM_MERGE=false`. Daily-to-weekly and weekly-to-monthly consolidation deduplicates facts via token Jaccard similarity and FTS5 overlap, preserving the highest effective score facts and dropping the rest.
- **Rationale**: Prevents a small model from corrupting facts through multi-stage rewriting. LLM rewriting is supported as an opt-in flag.

## Decision 5: Cross-Channel Identity Decoupling
- **Choice**: Separated canonical `users` from channel-specific `identities`.
- **Rationale**: Enables Telegram, WhatsApp, and Web channels to share a unified memory without merging based on fuzzy name heuristics. The `/link` 6-digit code flow enables secure, intentional account association.

## Decision 6: Priority Gate for LLM Inference
- **Choice**: Added an async priority gate in `app/services/llm_client.py` where interactive user turns preempt background extraction and decay jobs.
- **Rationale**: llama.cpp runs on a single inference slot. Background jobs must never block or delay an interactive conversational reply.

## Decision 7: Memory URLs Never Permitted in `allowed_urls`
- **Choice**: Memory retrieval text never expands `allowed_urls`.
- **Rationale**: Ensures that stored memory cannot be used as an injection vector to bypass URL verification in `GROUNDED_TEXT` mode.

## Decision 8: SQLite FTS5 Virtual Table with Automatic Triggers
- **Choice**: Created `memories_fts` using SQLite's FTS5 engine and bound `AFTER INSERT`, `AFTER DELETE`, and `AFTER UPDATE` triggers (`trg_memories_ai`, `trg_memories_ad`, `trg_memories_au`).
- **Rationale**: Keeps full-text keyword search synchronization atomic inside the existing SQLite WAL transaction without requiring application-level dual writes.

## Decision 9: Permanent Retention for Explicit Memory Instructions
- **Choice**: Facts extracted from explicit instructions (e.g. "remember that...") receive `source=MemorySource.EXPLICIT` and an effective score of 999.0, promoting them to `core` tier.
- **Rationale**: When a user explicitly commands Karna to remember something, dropping it after 30 days violates user intent. Only ephemeral observations decay unless reinforced.

## Decision 10: Backward-Compatible Schema Fallback
- **Choice**: Added an automatic `OperationalError` fallback in `repository.create_message()` that detects if `user_id` or `channel` columns are absent.
- **Rationale**: Ensures 100% backward compatibility with legacy test databases or external callers that instantiate isolated in-memory tables.

## Decision 11: Background Scheduler Cadence
- **Choice**: Scheduled nightly tier decay and online SQLite backup at 03:00 IST (21:30 UTC) and idle fact consolidation every 30 minutes.
- **Rationale**: Heavy consolidation, raw message purge, and online backup run during typical low-activity hours, while idle extraction batches recent conversations into structured profile updates without interfering with interactive turns.

