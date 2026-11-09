"""Application configuration for the Local AI Chatbot (Karna).

Loads settings from environment variables / `.env` via pydantic-settings.
Never prints secret values.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables, falling back to `.env` in the
    project root. Sensitive fields are excluded from string representations so
    they are never accidentally logged.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ----------------------------------------------------------
    app_env: str = Field(default="development")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)

    # --- Local LLM (llama.cpp server) ----------------------------------------
    llm_base_url: str = Field(default="")
    llm_model: Optional[str] = Field(default=None)
    llm_api_key: Optional[str] = Field(default=None)

    # --- Telegram Bot API ----------------------------------------------------
    telegram_bot_token: Optional[str] = Field(default=None)
    # Comma-separated allowed Telegram user IDs (integers, e.g. 123456789).
    telegram_allowed_user_ids: str = Field(default="")

    # --- Database -------------------------------------------------------------
    database_url: str = Field(default="sqlite:///./data/chatbot.db")

    # --- Runtime --------------------------------------------------------------
    max_history_messages: int = Field(default=10)
    request_timeout_seconds: int = Field(default=120)
    session_timeout_minutes: int = Field(default=30)

    # --- Web Search (SearXNG) -------------------------------------------------
    searxng_base_url: str = Field(default="http://127.0.0.1:8080")
    search_cache_ttl_seconds: int = Field(default=3600)

    # --- Web Extraction (Crawl4AI) -------------------------------------------
    crawler_timeout_seconds: int = Field(default=15)
    crawler_max_content_chars: int = Field(default=4000)

    # --- Official Integrations ------------------------------------------------
    github_token: Optional[str] = Field(default=None)
    reddit_client_id: Optional[str] = Field(default=None)
    reddit_client_secret: Optional[str] = Field(default=None)
    reddit_user_agent: str = Field(default="PersonalAI/1.0")
    openalex_email: Optional[str] = Field(default=None)
    rsshub_base_url: str = Field(default="https://rsshub.app")

    # --- Background Scheduler (APScheduler) -----------------------------------
    scheduler_enabled: bool = Field(default=True)
    rss_sync_interval_minutes: int = Field(default=30)
    github_sync_interval_hours: int = Field(default=6)
    openalex_sync_interval_hours: int = Field(default=12)
    reddit_sync_interval_hours: int = Field(default=4)

    # --- Monitoring (ChangeDetection.io) -------------------------------------
    changedetection_base_url: Optional[str] = Field(default=None)
    changedetection_api_key: Optional[str] = Field(default=None)
    monitoring_check_interval_hours: int = Field(default=2)

    # --- Long-Term Memory Subsystem (Model-Agnostic Profile) ------------------
    memory_context_tokens: int = Field(default=800)
    memory_max_prompt_tokens: int = Field(default=2048)
    memory_llm_extraction_enabled: bool = Field(default=True)
    memory_llm_merge: bool = Field(default=False)
    memory_grounding_min_overlap: float = Field(default=0.6)
    memory_extraction_batch_size: int = Field(default=5)
    memory_llm_timeout_s: int = Field(default=30)
    memory_llm_max_retries: int = Field(default=2)
    memory_embeddings_enabled: bool = Field(default=False)
    memory_embedding_url: str = Field(default="")
    memory_raw_retention_days: int = Field(default=2)
    memory_backup_retention: int = Field(default=7)
    memory_idle_extract_interval_minutes: int = Field(default=30)
    memory_idle_inactivity_minutes: int = Field(default=30)

    # --- Agent Delegation Subsystem (Cline & Antigravity) ---------------------
    agents_enabled: bool = Field(default=False)
    agents_panic: bool = Field(default=False)
    agents_allowed_user_ids: Optional[str] = Field(default=None)
    agent_workspaces_file: str = Field(default="config/agent_workspaces.yml")
    cline_bin: Optional[str] = Field(default=None)
    agy_bin: Optional[str] = Field(default=None)
    cline_extra_args: str = Field(default="")
    agy_extra_args: str = Field(default="")
    agent_confirm_ttl_s: int = Field(default=300)
    agent_job_timeout_s: int = Field(default=1800)
    agent_idle_timeout_s: int = Field(default=300)
    agent_max_concurrent: int = Field(default=1)
    agent_output_max_bytes: int = Field(default=5_000_000)
    agent_progress_interval_s: int = Field(default=20)
    agent_llm_summary: bool = Field(default=False)
    agent_run_as_user: Optional[str] = Field(default=None)
    agent_env_allowlist: str = Field(default="PATH,HOME,USER,SHELL,LANG,LC_ALL,TERM,ANTIGRAVITY_API_KEY")

    # --------------------------------------------------------------------------
    @property
    def allowed_telegram_user_ids(self) -> List[int]:
        """Return the list of allowed Telegram user IDs as integers."""
        raw = self.telegram_allowed_user_ids or ""
        ids: List[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                # Silently ignore non-integer entries to keep the app bootable.
                continue
        return ids

    @property
    def allowed_agent_user_ids(self) -> List[int]:
        """Return allowed agent Telegram user IDs; defaults to allowed_telegram_user_ids if unset."""
        raw = self.agents_allowed_user_ids
        if raw is None or not raw.strip():
            return self.allowed_telegram_user_ids
        ids: List[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue
        return ids

    @property
    def session_timeout_seconds(self) -> int:
        """Return session timeout in seconds (minimum 1 second)."""
        return max(1, self.session_timeout_minutes * 60)

    # --------------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - debugging only, secrets masked
        return (
            "Settings("
            f"app_env={self.app_env!r}, "
            f"host={self.host!r}, port={self.port!r}, "
            f"llm_base_url={self.llm_base_url!r}, "
            f"llm_model={'<set>' if self.llm_model else '<unset>'}, "
            f"telegram_configured={'<set>' if self.telegram_bot_token else '<unset>'}, "
            f"database_url={self.database_url!r}"
            ")"
        )

    def __str__(self) -> str:  # pragma: no cover - debugging only, secrets masked
        return self.__repr__()


settings = Settings()