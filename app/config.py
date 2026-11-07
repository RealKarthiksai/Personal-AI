"""Application configuration wrapper.

Reuses the settings loader from config/settings.py so all
environment variables are defined in .env / .env.example and secrets are never
hardcoded or printed.
"""

from __future__ import annotations

from config.settings import settings as _base_settings


class Config:
    """Thin wrapper exposing typed configuration used by the application."""

    def __init__(self) -> None:
        s = _base_settings
        self.app_env = s.app_env
        self.host = s.host
        self.port = s.port
        self.database_url = s.database_url
        self.max_history_messages = s.max_history_messages
        self.request_timeout_seconds = s.request_timeout_seconds
        self.session_timeout_minutes = s.session_timeout_minutes
        self.session_timeout_seconds = s.session_timeout_seconds

        # Local LLM (llama.cpp OpenAI-compatible API)
        self.llm_base_url = s.llm_base_url.rstrip("/") if s.llm_base_url else ""
        self.llm_model = s.llm_model
        self.llm_api_key = s.llm_api_key

        # Telegram Bot API (active channel)
        self.telegram_bot_token = s.telegram_bot_token
        self.telegram_allowed_user_ids = s.telegram_allowed_user_ids
        self.allowed_telegram_user_ids = s.allowed_telegram_user_ids

        # Web Search & Extraction
        self.searxng_base_url = s.searxng_base_url.rstrip("/") if s.searxng_base_url else ""
        self.search_cache_ttl_seconds = s.search_cache_ttl_seconds
        self.crawler_timeout_seconds = s.crawler_timeout_seconds
        self.crawler_max_content_chars = s.crawler_max_content_chars

        # Official Integrations
        self.github_token = s.github_token
        self.reddit_client_id = s.reddit_client_id
        self.reddit_client_secret = s.reddit_client_secret
        self.reddit_user_agent = s.reddit_user_agent
        self.openalex_email = s.openalex_email
        self.rsshub_base_url = s.rsshub_base_url

        # Scheduler
        self.scheduler_enabled = s.scheduler_enabled
        self.rss_sync_interval_minutes = s.rss_sync_interval_minutes
        self.github_sync_interval_hours = s.github_sync_interval_hours
        self.openalex_sync_interval_hours = s.openalex_sync_interval_hours
        self.reddit_sync_interval_hours = s.reddit_sync_interval_hours

        # Monitoring
        self.changedetection_base_url = s.changedetection_base_url
        self.changedetection_api_key = s.changedetection_api_key
        self.monitoring_check_interval_hours = s.monitoring_check_interval_hours

        # Memory Subsystem
        self.memory_context_tokens = s.memory_context_tokens
        self.memory_max_prompt_tokens = s.memory_max_prompt_tokens
        self.memory_llm_extraction_enabled = s.memory_llm_extraction_enabled
        self.memory_llm_merge = s.memory_llm_merge
        self.memory_grounding_min_overlap = s.memory_grounding_min_overlap
        self.memory_extraction_batch_size = s.memory_extraction_batch_size
        self.memory_llm_timeout_s = s.memory_llm_timeout_s
        self.memory_llm_max_retries = s.memory_llm_max_retries
        self.memory_embeddings_enabled = s.memory_embeddings_enabled
        self.memory_embedding_url = s.memory_embedding_url
        self.memory_raw_retention_days = s.memory_raw_retention_days
        self.memory_backup_retention = s.memory_backup_retention
        self.memory_idle_extract_interval_minutes = s.memory_idle_extract_interval_minutes
        self.memory_idle_inactivity_minutes = s.memory_idle_inactivity_minutes

    def is_telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)

    def is_llm_configured(self) -> bool:
        return bool(self.llm_base_url)

    def is_searxng_configured(self) -> bool:
        return bool(self.searxng_base_url)

    def is_changedetection_configured(self) -> bool:
        return bool(self.changedetection_base_url)

    def __repr__(self) -> str:  # pragma: no cover - debugging only, secrets masked
        return (
            "Config("
            f"app_env={self.app_env!r}, "
            f"llm_base_url={self.llm_base_url!r}, "
            f"llm_model={'<set>' if self.llm_model else '<unset>'}, "
            f"telegram_configured={self.is_telegram_configured()}"
            ")"
        )


config = Config()