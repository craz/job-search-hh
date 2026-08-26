"""Unit tests for R1.6 recovery taxonomy."""

from __future__ import annotations

from job_search_hh.recovery import (
    RECOVERY_CAPTCHA_OR_ACTION,
    RECOVERY_EXTERNAL_LIMITATION,
    RECOVERY_NETWORK,
    RECOVERY_NONE,
    RECOVERY_REAUTH,
    classify_recovery,
    with_recovery,
)


def test_classify_reauth_states() -> None:
    assert (
        classify_recovery(status="expired", code="access_token_expired")["kind"] == RECOVERY_REAUTH
    )
    assert (
        classify_recovery(status="not_authorized", code="me_unauthorized")["kind"]
        == RECOVERY_REAUTH
    )
    assert (
        classify_recovery(status="available", code="connection_expired")["kind"] == RECOVERY_REAUTH
    )


def test_classify_captcha_and_action_required() -> None:
    assert (
        classify_recovery(status="action_required", code="browser_captcha_or_action_required")[
            "kind"
        ]
        == RECOVERY_CAPTCHA_OR_ACTION
    )
    assert (
        classify_recovery(
            status="action_required",
            code="operator_confirm_required",
            action_code="confirm_login",
        )["kind"]
        == RECOVERY_CAPTCHA_OR_ACTION
    )


def test_classify_external_and_network() -> None:
    assert (
        classify_recovery(status="permission_blocked", code="me_forbidden")["kind"]
        == RECOVERY_EXTERNAL_LIMITATION
    )
    assert (
        classify_recovery(status="unavailable", code="me_upstream_failure")["kind"]
        == RECOVERY_NETWORK
    )


def test_with_recovery_is_additive() -> None:
    payload = with_recovery(
        {
            "status": "connected",
            "code": "ready",
            "action": {"code": "none"},
        }
    )
    assert payload["status"] == "connected"
    assert payload["recovery"] == {"kind": RECOVERY_NONE, "operator_action": "none"}
