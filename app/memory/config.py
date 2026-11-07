"""Memory subsystem configuration and model profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import config


@dataclass(frozen=True)
class MemoryModelProfile:
    """Model-dependent configuration for the memory subsystem."""

    context_tokens: int = 800
    max_prompt_tokens: int = 2048
    llm_extraction_enabled: bool = True
    llm_merge: bool = False
    grounding_min_overlap: float = 0.6
    extraction_batch_size: int = 5
    llm_timeout_s: int = 30
    llm_max_retries: int = 2
    embeddings_enabled: bool = False
    embedding_url: str = ""
    raw_retention_days: int = 2
    backup_retention: int = 7
    idle_extract_interval_minutes: int = 30
    idle_inactivity_minutes: int = 30


def get_memory_profile() -> MemoryModelProfile:
    """Return runtime memory model profile sourced from application configuration."""
    return MemoryModelProfile(
        context_tokens=config.memory_context_tokens,
        max_prompt_tokens=config.memory_max_prompt_tokens,
        llm_extraction_enabled=config.memory_llm_extraction_enabled,
        llm_merge=config.memory_llm_merge,
        grounding_min_overlap=config.memory_grounding_min_overlap,
        extraction_batch_size=config.memory_extraction_batch_size,
        llm_timeout_s=config.memory_llm_timeout_s,
        llm_max_retries=config.memory_llm_max_retries,
        embeddings_enabled=config.memory_embeddings_enabled,
        embedding_url=config.memory_embedding_url,
        raw_retention_days=config.memory_raw_retention_days,
        backup_retention=config.memory_backup_retention,
        idle_extract_interval_minutes=config.memory_idle_extract_interval_minutes,
        idle_inactivity_minutes=config.memory_idle_inactivity_minutes,
    )
