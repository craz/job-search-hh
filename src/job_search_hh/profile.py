"""Product-facing HH account/profile context from official GET /me (R1.2).

Normalized contract only — never proxies the raw `/me` body to Web/domain.
Connection (R1.1) and profile capability stay separate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from job_search_hh.config import Settings
from job_search_hh.connection import (
    STATUS_ACTION_REQUIRED,
    STATUS_CONNECTED,
    STATUS_EXPIRED,
    STATUS_NOT_AUTHORIZED,
    STATUS_UNAVAILABLE,
    connection_status,
)
from job_search_hh.live_auth import load_access_token
from job_search_hh.session import SessionPaths

PROFILE_AVAILABLE = "available"
PROFILE_NOT_AUTHORIZED = "not_authorized"
PROFILE_EXPIRED = "expired"
PROFILE_PERMISSION_BLOCKED = "permission_blocked"
PROFILE_UNAVAILABLE = "unavailable"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _display_name(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("first_name", "last_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if parts:
        return " ".join(parts)
    mid = payload.get("middle_name") or payload.get("mid_name")
    if isinstance(mid, str) and mid.strip():
        return mid.strip()
    return None


def _normalize_account(payload: dict[str, Any]) -> dict[str, str] | None:
    external_id = payload.get("id")
    if not isinstance(external_id, str) or not external_id.strip():
        return None
    account: dict[str, str] = {"external_id": external_id.strip()}
    name = _display_name(payload)
    if name:
        account["display_name"] = name
    email = payload.get("email")
    if isinstance(email, str) and email.strip():
        account["email"] = email.strip()
    return account


def _fetch_me(
    *,
    base_url: str,
    user_agent: str,
    access_token: str,
    timeout_seconds: float,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    """GET /me; returns (http_status, json_dict_or_none, error_code)."""
    url = f"{base_url.rstrip('/')}/me"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, None, "invalid_hh_url"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            status = int(response.status)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return status, None, "invalid_hh_response"
            if not isinstance(payload, dict):
                return status, None, "invalid_hh_response"
            return status, payload, None
    except urllib.error.HTTPError as error:
        return int(error.code), None, f"http_{error.code}"
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None, None, "upstream_failure"


def account_profile(
    paths: SessionPaths | None = None,
    *,
    settings: Settings | None = None,
    me_fetcher: Any | None = None,
) -> dict[str, Any]:
    """Return normalized HH account context using R1.1 connection + GET /me.

    Does not claim resume-list capability. Never includes tokens or raw `/me`.
    """
    checked_at = _utc_now()
    connection = connection_status(paths)
    connection_state = str(connection.get("status") or STATUS_UNAVAILABLE)

    base: dict[str, Any] = {
        "account": None,
        "connection_status": connection_state,
        "checked_at": checked_at,
    }

    if connection_state == STATUS_NOT_AUTHORIZED:
        return {
            **base,
            "status": PROFILE_NOT_AUTHORIZED,
            "code": "connection_not_authorized",
        }
    if connection_state == STATUS_EXPIRED:
        return {
            **base,
            "status": PROFILE_EXPIRED,
            "code": "connection_expired",
        }
    if connection_state == STATUS_ACTION_REQUIRED:
        return {
            **base,
            "status": PROFILE_NOT_AUTHORIZED,
            "code": str(connection.get("code") or "connection_action_required"),
        }
    if connection_state != STATUS_CONNECTED:
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": str(connection.get("code") or "connection_unavailable"),
        }

    try:
        token = load_access_token(paths)
    except (OSError, ValueError, TypeError):
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": "token_read_failed",
        }
    if not token:
        return {
            **base,
            "status": PROFILE_NOT_AUTHORIZED,
            "code": "access_token_missing",
        }

    cfg = settings or Settings.from_env()
    fetch = me_fetcher or _fetch_me
    http_status, payload, fetch_error = fetch(
        base_url=cfg.hh_api_url,
        user_agent=cfg.user_agent,
        access_token=token,
        timeout_seconds=cfg.timeout_seconds,
    )

    if http_status == 401:
        return {
            **base,
            "status": PROFILE_NOT_AUTHORIZED,
            "code": "me_unauthorized",
        }
    if http_status == 403:
        return {
            **base,
            "status": PROFILE_PERMISSION_BLOCKED,
            "code": "me_forbidden",
        }
    if http_status is None or fetch_error == "upstream_failure":
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": "me_upstream_failure",
        }
    if fetch_error == "invalid_hh_response" or payload is None:
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": "me_invalid_response",
        }
    if http_status != 200:
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": f"me_http_{http_status}",
        }

    account = _normalize_account(payload)
    if account is None:
        return {
            **base,
            "status": PROFILE_UNAVAILABLE,
            "code": "me_missing_identity",
        }

    return {
        **base,
        "status": PROFILE_AVAILABLE,
        "account": account,
        "code": "ready",
    }
