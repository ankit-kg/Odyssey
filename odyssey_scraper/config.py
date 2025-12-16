from __future__ import annotations

import os
from dataclasses import dataclass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    subreddit: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    reddit_username: str | None
    reddit_password: str | None
    reddit_refresh_token: str | None
    supabase_url: str | None
    supabase_service_role_key: str | None

    @staticmethod
    def from_env(*, require_supabase: bool = True) -> "Config":
        return Config(
            subreddit=os.getenv("SUBREDDIT", "churningmarketplace"),
            reddit_client_id=_require_env("REDDIT_CLIENT_ID"),
            reddit_client_secret=_require_env("REDDIT_CLIENT_SECRET"),
            reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "odyssey-scraper/1.0"),
            reddit_username=os.getenv("REDDIT_USERNAME"),
            reddit_password=os.getenv("REDDIT_PASSWORD"),
            reddit_refresh_token=os.getenv("REDDIT_REFRESH_TOKEN"),
            supabase_url=_require_env("SUPABASE_URL") if require_supabase else os.getenv("SUPABASE_URL"),
            supabase_service_role_key=_require_env("SUPABASE_SERVICE_ROLE_KEY")
            if require_supabase
            else os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        )


