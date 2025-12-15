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
    supabase_url: str
    supabase_service_role_key: str

    @staticmethod
    def from_env() -> "Config":
        return Config(
            subreddit=os.getenv("SUBREDDIT", "churningmarketplace"),
            reddit_client_id=_require_env("REDDIT_CLIENT_ID"),
            reddit_client_secret=_require_env("REDDIT_CLIENT_SECRET"),
            reddit_user_agent=os.getenv("REDDIT_USER_AGENT", "odyssey-scraper/1.0"),
            supabase_url=_require_env("SUPABASE_URL"),
            supabase_service_role_key=_require_env("SUPABASE_SERVICE_ROLE_KEY"),
        )


