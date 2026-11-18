"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    cors_origins: list[str]
    search_rate_limit_per_min: int


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:8080")
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://hfr:hfr@localhost:5432/hfr"),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        search_rate_limit_per_min=int(os.getenv("SEARCH_RATE_LIMIT_PER_MIN", "60")),
    )
