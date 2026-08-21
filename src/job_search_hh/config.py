"""Runtime settings for HH sync and gated apply."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Bounded Core/HH endpoints and conservative write gates."""

    core_url: str
    hh_api_url: str
    user_agent: str
    timeout_seconds: float
    external_writes_enabled: bool
    apply_limit_per_run: int

    @classmethod
    def from_env(cls) -> Settings:
        """Load conservative defaults suitable for local Compose Core."""
        return cls(
            core_url=os.getenv("CORE_API_URL", "http://127.0.0.1:8000").rstrip("/"),
            hh_api_url=os.getenv("JOB_SEARCH_HH_API_URL", "https://api.hh.ru").rstrip("/"),
            user_agent=os.getenv(
                "JOB_SEARCH_HH_USER_AGENT",
                "job-search-hh/0.1 (+https://github.com/local/job-search-hh; read-only)",
            ),
            timeout_seconds=float(os.getenv("JOB_SEARCH_HH_TIMEOUT_SECONDS", "20")),
            external_writes_enabled=_env_flag("JOB_SEARCH_HH_EXTERNAL_WRITES_ENABLED", False),
            apply_limit_per_run=max(1, int(os.getenv("JOB_SEARCH_HH_APPLY_LIMIT", "1"))),
        )
