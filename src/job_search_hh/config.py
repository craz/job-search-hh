"""Runtime settings for read-only HH vacancy sync."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Bounded Core and HH API endpoints without secrets in capability output."""

    core_url: str
    hh_api_url: str
    user_agent: str
    timeout_seconds: float

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
        )
