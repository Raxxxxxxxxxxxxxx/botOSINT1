"""Environment-driven application settings.

All configuration is read from environment variables (populated from a
``.env`` file via ``python-dotenv`` in local development, or injected
directly by Railway in production). No secrets are hardcoded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable with a fallback default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    """Parse an integer environment variable with a fallback default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    """Parse a float environment variable with a fallback default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the bot's runtime configuration."""

    # --- Telegram (aiogram) ---
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    target_chat_id: str = field(default_factory=lambda: os.getenv("TARGET_CHAT_ID", ""))

    # --- Admin panel (optional; the bot's owner only) ---
    # 0 (unset) means the admin panel denies everyone — fail closed, not open.
    admin_id: int = field(default_factory=lambda: _get_int("ADMIN_ID", 0))

    # --- Database ---
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db"
        )
    )

    # --- Logging ---
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_dir: str = field(default_factory=lambda: os.getenv("LOG_DIR", "./logs"))
    sentry_dsn: str | None = field(default_factory=lambda: os.getenv("SENTRY_DSN") or None)

    # --- HTTP fetching (RSS / HTML adapters) ---
    http_timeout_seconds: float = field(
        default_factory=lambda: _get_float("HTTP_TIMEOUT_SECONDS", 15.0)
    )
    http_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "HTTP_USER_AGENT",
            "Mozilla/5.0 (compatible; RaqqaNewsBot/1.0; +https://t.me/)",
        )
    )

    # --- Scheduling ---
    scheduler_default_jitter_seconds: int = field(
        default_factory=lambda: _get_int("SCHEDULER_DEFAULT_JITTER_SECONDS", 20)
    )
    circuit_breaker_failure_threshold: int = field(
        default_factory=lambda: _get_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
    )
    circuit_breaker_cooldown_cycles: int = field(
        default_factory=lambda: _get_int("CIRCUIT_BREAKER_COOLDOWN_CYCLES", 6)
    )

    # --- Deduplication ---
    dedup_fuzzy_threshold: int = field(
        default_factory=lambda: _get_int("DEDUP_FUZZY_THRESHOLD", 88)
    )
    dedup_window_hours: int = field(
        default_factory=lambda: _get_int("DEDUP_WINDOW_HOURS", 48)
    )
    dedup_window_max_items: int = field(
        default_factory=lambda: _get_int("DEDUP_WINDOW_MAX_ITEMS", 500)
    )

    # --- Geographic relevance filter ---
    geo_fuzzy_threshold: int = field(
        default_factory=lambda: _get_int("GEO_FUZZY_THRESHOLD", 85)
    )

    # --- Publishing / rate limiting ---
    publish_min_interval_seconds: float = field(
        default_factory=lambda: _get_float("PUBLISH_MIN_INTERVAL_SECONDS", 1.2)
    )

    # --- AI summarization (optional, external API only — never a local model) ---
    ai_summary_enabled: bool = field(
        default_factory=lambda: _get_bool("AI_SUMMARY_ENABLED", False)
    )
    ai_api_key: str | None = field(default_factory=lambda: os.getenv("AI_API_KEY") or None)
    ai_api_base_url: str = field(
        default_factory=lambda: os.getenv("AI_API_BASE_URL", "https://api.openai.com/v1")
    )
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "gpt-4o-mini"))

    # --- Facebook Page posts (via Apify actor; optional, per-source opt-in) ---
    apify_api_token: str | None = field(default_factory=lambda: os.getenv("APIFY_API_TOKEN") or None)
    apify_facebook_actor_id: str = field(
        default_factory=lambda: os.getenv(
            "APIFY_FACEBOOK_ACTOR_ID", "apify~facebook-posts-scraper"
        )
    )
    apify_facebook_results_limit: int = field(
        default_factory=lambda: _get_int("APIFY_FACEBOOK_RESULTS_LIMIT", 20)
    )
    apify_facebook_initial_lookback_days: int = field(
        default_factory=lambda: _get_int("APIFY_FACEBOOK_INITIAL_LOOKBACK_DAYS", 3)
    )
    apify_run_timeout_seconds: float = field(
        default_factory=lambda: _get_float("APIFY_RUN_TIMEOUT_SECONDS", 320.0)
    )

    # --- Optional Telegram-channel monitoring (Telethon userbot) ---
    telethon_enabled: bool = field(
        default_factory=lambda: _get_bool("TELETHON_ENABLED", False)
    )
    telethon_api_id: int = field(default_factory=lambda: _get_int("TELETHON_API_ID", 0))
    telethon_api_hash: str = field(
        default_factory=lambda: os.getenv("TELETHON_API_HASH", "")
    )
    telethon_session_name: str = field(
        default_factory=lambda: os.getenv("TELETHON_SESSION_NAME", "./data/telethon_session")
    )

    def validate(self) -> None:
        """Raise a clear error if required configuration is missing.

        Called once at startup so misconfiguration fails fast instead of
        surfacing as a confusing error deep inside the pipeline.
        """
        missing: list[str] = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.target_chat_id:
            missing.append("TARGET_CHAT_ID")
        if self.ai_summary_enabled and not self.ai_api_key:
            missing.append("AI_API_KEY (required because AI_SUMMARY_ENABLED=true)")
        if self.telethon_enabled and (not self.telethon_api_id or not self.telethon_api_hash):
            missing.append(
                "TELETHON_API_ID/TELETHON_API_HASH (required because TELETHON_ENABLED=true)"
            )
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
