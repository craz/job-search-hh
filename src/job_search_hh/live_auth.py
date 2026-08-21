"""Gates and token loading for authenticated HH API reads (never HH writes)."""

from __future__ import annotations

import os
from pathlib import Path

from job_search_hh.session import SessionPaths, auth_status


class LiveAuthError(Exception):
    """Stable refusal when operator session or API token is not ready."""


def load_access_token(paths: SessionPaths | None = None) -> str:
    """Load Bearer token from env or state file; never return cookies or logs."""
    env_token = os.getenv("JOB_SEARCH_HH_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    default_file = resolved.state_dir / "access_token"
    token_file = Path(os.getenv("JOB_SEARCH_HH_ACCESS_TOKEN_FILE", str(default_file)))
    if token_file.is_file():
        return token_file.read_text(encoding="utf-8").strip()
    return ""


def require_authenticated_read(paths: SessionPaths | None = None) -> str:
    """Require confirmed operator login and a non-empty API access token."""
    status = auth_status(paths)
    if not status["login_ready"]:
        raise LiveAuthError("login_not_ready")
    token = load_access_token(paths)
    if not token:
        raise LiveAuthError("access_token_missing")
    return token
