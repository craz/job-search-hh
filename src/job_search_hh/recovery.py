"""Unified operator recovery taxonomy for HH product surfaces (R1.6 / US-00.6).

Additive ``recovery`` object on connection / account / resumes envelopes so CLI
and Web can distinguish re-auth, CAPTCHA/action-required, external permission
limits, and network failures without inventing a second status enum.
"""

from __future__ import annotations

from typing import Any

RECOVERY_NONE = "none"
RECOVERY_REAUTH = "reauth"
RECOVERY_CAPTCHA_OR_ACTION = "captcha_or_action_required"
RECOVERY_EXTERNAL_LIMITATION = "external_limitation"
RECOVERY_NETWORK = "network_failure"

_STATUS_REAUTH = frozenset({"not_authorized", "expired"})
_STATUS_ACTION = frozenset({"action_required"})
_STATUS_EXTERNAL = frozenset({"permission_blocked"})
_CODE_NETWORK = frozenset(
    {
        "me_upstream_failure",
        "browser_resume_read_failed",
        "connection_read_failed",
        "network_failure",
        "upstream_failure",
    }
)
_CODE_CAPTCHA = frozenset(
    {
        "captcha_or_action_required",
        "browser_captcha_or_action_required",
        "operator_confirm_required",
        "access_token_missing",
    }
)
_CODE_EXTERNAL = frozenset(
    {
        "me_forbidden",
        "browser_resume_forbidden",
        "permission_denied",
    }
)
_CODE_REAUTH = frozenset(
    {
        "me_unauthorized",
        "access_token_expired",
        "connection_expired",
        "connection_not_authorized",
        "browser_login_required",
        "browser_session_not_logged_in",
        "not_authorized",
    }
)


def classify_recovery(
    *,
    status: str | None,
    code: str | None = None,
    action_code: str | None = None,
) -> dict[str, str]:
    """Map surface status/code/action into a stable recovery kind."""
    status_value = (status or "").strip()
    code_value = (code or "").strip()
    action_value = (action_code or "none").strip() or "none"

    if code_value in _CODE_CAPTCHA or (
        status_value in _STATUS_ACTION and action_value in {"confirm_login", "acquire_token"}
    ):
        kind = RECOVERY_CAPTCHA_OR_ACTION
    elif code_value in _CODE_EXTERNAL or status_value in _STATUS_EXTERNAL:
        kind = RECOVERY_EXTERNAL_LIMITATION
    elif code_value in _CODE_NETWORK or code_value.startswith("me_http_"):
        kind = RECOVERY_NETWORK
    elif code_value in _CODE_REAUTH or status_value in _STATUS_REAUTH:
        kind = RECOVERY_REAUTH
    elif status_value in _STATUS_ACTION:
        kind = RECOVERY_CAPTCHA_OR_ACTION
    else:
        kind = RECOVERY_NONE

    return {"kind": kind, "operator_action": action_value}


def with_recovery(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach ``recovery`` derived from existing status/code/action fields."""
    raw_action = payload.get("action")
    action: dict[str, Any] = raw_action if isinstance(raw_action, dict) else {}
    action_code = action.get("code") if isinstance(action.get("code"), str) else "none"
    enriched = dict(payload)
    enriched["recovery"] = classify_recovery(
        status=str(payload.get("status") or ""),
        code=str(payload.get("code") or "") if payload.get("code") is not None else None,
        action_code=action_code,
    )
    return enriched
