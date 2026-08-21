"""Executable pytest-bdd bindings for loopback OAuth callback acquire."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.oauth import OAuthSettings, token_status
from job_search_hh.oauth_callback import oauth_acquire
from job_search_hh.session import SessionPaths

scenarios("../features/oauth_loopback_callback.feature")


@given("OAuth credentials и loopback redirect", target_fixture="oauth_ctx")
def oauth_credentials(tmp_path: Path, monkeypatch: Any) -> dict[str, Any]:
    state = tmp_path / "state"
    profile = tmp_path / "profile"
    state.mkdir()
    profile.mkdir()
    monkeypatch.setenv("HH_STATE_DIR", str(state))
    monkeypatch.setenv("HH_PROFILE_DIR", str(profile))
    monkeypatch.delenv("JOB_SEARCH_HH_ACCESS_TOKEN", raising=False)
    redirect = "http://127.0.0.1:8769/oauth/callback"
    settings = OAuthSettings(
        client_id="cid",
        client_secret="csecret",
        redirect_uri=redirect,
        auth_host="https://hh.ru",
        user_agent="ua",
        timeout_seconds=5.0,
    )
    return {
        "paths": SessionPaths(state_dir=state, profile_dir=profile),
        "settings": settings,
        "redirect": redirect,
    }


@when("listener получает authorization code", target_fixture="acquire_report")
def listener_gets_code(oauth_ctx: dict[str, Any]) -> dict[str, Any]:
    def fake_exchange(code: str, *, paths: Any = None, settings: Any = None) -> dict[str, Any]:
        del settings
        assert code == "loopback-code"
        from job_search_hh.oauth import set_access_token

        return set_access_token("loopback-secret-token", paths=paths)

    def hit_callback() -> None:
        for _ in range(50):
            try:
                urllib.request.urlopen(  # noqa: S310 - local loopback test only
                    "http://127.0.0.1:8769/oauth/callback?code=loopback-code&state=job-search-hh",
                    timeout=0.5,
                )
                return
            except OSError:
                continue

    thread = threading.Thread(target=hit_callback, daemon=True)
    thread.start()
    report = oauth_acquire(
        paths=oauth_ctx["paths"],
        settings=oauth_ctx["settings"],
        wait_seconds=5.0,
        detach=False,
        exchange=fake_exchange,
    )
    thread.join(timeout=2)
    return report


@then("token-status показывает access_token_present")
def token_present(acquire_report: dict[str, Any], oauth_ctx: dict[str, Any]) -> None:
    assert acquire_report["access_token_present"] is True
    assert acquire_report["callback_received"] is True
    assert token_status(oauth_ctx["paths"])["access_token_present"] is True


@then("отчёт не содержит сырой access_token")
def no_raw_secret(acquire_report: dict[str, Any]) -> None:
    dumped = json.dumps(acquire_report, ensure_ascii=False)
    assert '"access_token":' not in dumped
    assert "loopback-secret-token" not in dumped
    assert "csecret" not in dumped
