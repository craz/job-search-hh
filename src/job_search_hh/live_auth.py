"""Gates and token loading for authenticated HH API reads (never HH writes)."""

from __future__ import annotations

import contextlib
import os
import time

from job_search_hh.oauth import (
    OAuthError,
    load_token_record,
    plain_access_token_path,
    refresh_token_record,
    token_status,
)
from job_search_hh.session import SessionPaths, auth_status


class LiveAuthError(Exception):
    """Stable refusal when operator session or API token is not ready."""


def load_access_token(paths: SessionPaths | None = None) -> str:
    """Load Bearer token from env or private state files; never return cookies."""
    env_token = os.getenv("JOB_SEARCH_HH_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    record = load_token_record(paths)
    if record is not None:
        expires_at = record.expires_at
        if expires_at is not None and time.time() >= expires_at - 60:
            if record.refresh_token:
                with contextlib.suppress(OAuthError):
                    record = refresh_token_record(paths)
            elif time.time() >= expires_at:
                return ""
        return record.access_token

    plain = plain_access_token_path(paths)
    if plain.is_file():
        return plain.read_text(encoding="utf-8").strip()
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


def access_token_status(paths: SessionPaths | None = None) -> dict[str, object]:
    """Public token presence report; delegates to oauth.token_status."""
    return token_status(paths)
