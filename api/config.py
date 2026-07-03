from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

from dotenv import load_dotenv


REQUIRED_ENV_VARS = (
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "API_BASE_URL",
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str
    api_base_url: str
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_channel_id: str = ""
    voyage_api_key: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    app_timezone: str = "America/Los_Angeles"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    stripe_pro_price_id: str = ""
    stripe_scale_price_id: str = ""


def _load_dotenv_files() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(override=False)


def _redis_url() -> str:
    explicit_url = os.getenv("REDIS_URL", "").strip()
    if explicit_url:
        return explicit_url

    upstash_rest_url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
    upstash_rest_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if upstash_rest_url and upstash_rest_token:
        host = urlparse(upstash_rest_url).hostname
        if host:
            return f"rediss://default:{quote(upstash_rest_token, safe='')}@{host}:6379"

    return "redis://localhost:6379/0"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_settings() -> Settings:
    _load_dotenv_files()
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {missing_list}")

    return Settings(
        database_url=_env("DATABASE_URL"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        slack_bot_token=_env("SLACK_BOT_TOKEN"),
        slack_signing_secret=_env("SLACK_SIGNING_SECRET"),
        slack_channel_id=_env("SLACK_CHANNEL_ID"),
        api_base_url=_env("API_BASE_URL").rstrip("/"),
        voyage_api_key=_env("VOYAGE_API_KEY") or None,
        redis_url=_redis_url(),
        app_timezone=_env("APP_TIMEZONE", "America/Los_Angeles"),
        supabase_url=_env("SUPABASE_URL").rstrip("/"),
        supabase_anon_key=_env("SUPABASE_ANON_KEY"),
        stripe_secret_key=_env("STRIPE_SECRET_KEY"),
        stripe_webhook_secret=_env("STRIPE_WEBHOOK_SECRET"),
        stripe_price_id=_env("STRIPE_PRICE_ID"),
        stripe_pro_price_id=_env("STRIPE_PRO_PRICE_ID"),
        stripe_scale_price_id=_env("STRIPE_SCALE_PRICE_ID"),
    )


settings = load_settings()
