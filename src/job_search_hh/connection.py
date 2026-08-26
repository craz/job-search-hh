"""Product-facing HeadHunter connection/session status (R1.1).

Maps existing auth/session/token markers into a stable contract without exposing
secrets or claiming endpoint capabilities (/me, resumes, negotiations).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_search_hh.oauth import token_status
from job_search_hh.session import SessionPaths, auth_status

STATUS_CONNECTED = "connected"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_EXPIRED = "expired"
STATUS_ACTION_REQUIRED = "action_required"
STATUS_UNAVAILABLE = "unavailable"

ACTION_NONE = "none"
ACTION_OPEN_LOGIN = "open_login"
ACTION_CONFIRM_LOGIN = "confirm_login"
ACTION_ACQUIRE_TOKEN = "acquire_token"
ACTION_RECONNECT = "reconnect"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _action(
    code: str,
    *,
    novnc_url: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code}
    if novnc_url:
        payload["novnc_url"] = novnc_url
    return payload


def _novnc_url_if_configured(auth: dict[str, Any]) -> str | None:
    if not auth.get("novnc_configured"):
        return None
    from job_search_hh.session import novnc_public_url

    return novnc_public_url()


def connection_status(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Return product connection state from existing session/token sources only.

    CONNECTED means Job Search can use the authenticated HH context (operator
    login confirmed and a non-expired access token is present). It does **not**
    assert that every HH API endpoint is permitted.
    """
    checked_at = _utc_now()
    try:
        auth = auth_status(paths)
        tokens = token_status(paths)
    except (OSError, ValueError, TypeError) as error:
        return {
            "status": STATUS_UNAVAILABLE,
            "authenticated": False,
            "login_ready": False,
            "expired": False,
            "expires_at": None,
            "action": _action(ACTION_NONE),
            "code": "connection_read_failed",
            "detail": type(error).__name__,
            "checked_at": checked_at,
        }

    auth_session = str(auth.get("auth_session") or "absent")
    login_ready = bool(auth.get("login_ready"))
    token_present = bool(tokens.get("access_token_present"))
    expired = bool(tokens.get("expired"))
    expires_at = tokens.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, str):
        expires_at = None
    novnc_url = _novnc_url_if_configured(auth)

    base = {
        "login_ready": login_ready,
        "expired": expired,
        "expires_at": expires_at,
        "checked_at": checked_at,
    }

    if auth_session == "invalid":
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "authenticated": False,
            "action": _action(ACTION_NONE),
            "code": "session_marker_invalid",
        }

    if auth_session == "pending_operator":
        return {
            **base,
            "status": STATUS_ACTION_REQUIRED,
            "authenticated": False,
            "action": _action(ACTION_CONFIRM_LOGIN, novnc_url=novnc_url),
            "code": "operator_confirm_required",
        }

    if expired and token_present:
        return {
            **base,
            "status": STATUS_EXPIRED,
            "authenticated": False,
            "action": _action(ACTION_RECONNECT, novnc_url=novnc_url),
            "code": "access_token_expired",
        }

    if auth_session == "present" and not login_ready:
        # Marker present but chromium/runtime not ready for operator login path.
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "authenticated": False,
            "action": _action(ACTION_NONE),
            "code": "login_runtime_unavailable",
        }

    if login_ready and token_present and not expired:
        return {
            **base,
            "status": STATUS_CONNECTED,
            "authenticated": True,
            "action": _action(ACTION_NONE),
            "code": "ready",
        }

    if login_ready and not token_present:
        return {
            **base,
            "status": STATUS_ACTION_REQUIRED,
            "authenticated": False,
            "action": _action(ACTION_ACQUIRE_TOKEN),
            "code": "access_token_missing",
        }

    if auth_session == "absent" or not token_present:
        return {
            **base,
            "status": STATUS_NOT_AUTHORIZED,
            "authenticated": False,
            "action": _action(ACTION_OPEN_LOGIN, novnc_url=novnc_url),
            "code": "not_authorized",
        }

    return {
        **base,
        "status": STATUS_UNAVAILABLE,
        "authenticated": False,
        "action": _action(ACTION_NONE),
        "code": "connection_state_unknown",
    }
