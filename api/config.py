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


def _load_dotenv_files() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(override=False)


def _redis_url() -> str:
    explicit_url = os.getenv("REDIS_URL")
    if explicit_url:
        return explicit_url

    upstash_rest_url = os.getenv("UPSTASH_REDIS_REST_URL")
    upstash_rest_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if upstash_rest_url and upstash_rest_token:
        host = urlparse(upstash_rest_url).hostname
        if host:
            return f"rediss://default:{quote(upstash_rest_token, safe='')}@{host}:6379"

    return "redis://localhost:6379/0"


def load_settings() -> Settings:
    _load_dotenv_files()
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {missing_list}")

    return Settings(
        database_url=os.environ["DATABASE_URL"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
        slack_channel_id=os.getenv("SLACK_CHANNEL_ID", ""),
        api_base_url=os.environ["API_BASE_URL"].rstrip("/"),
        voyage_api_key=os.getenv("VOYAGE_API_KEY"),
        redis_url=_redis_url(),
        app_timezone=os.getenv("APP_TIMEZONE", "America/Los_Angeles"),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
        stripe_price_id=os.getenv("STRIPE_PRICE_ID", ""),
    )


settings = load_settings()
