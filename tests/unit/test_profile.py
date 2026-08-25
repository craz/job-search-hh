"""Unit tests for normalized HH account/profile (R1.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_search_hh.oauth import set_access_token
from job_search_hh.profile import (
    PROFILE_AVAILABLE,
    PROFILE_EXPIRED,
    PROFILE_NOT_AUTHORIZED,
    PROFILE_PERMISSION_BLOCKED,
    PROFILE_UNAVAILABLE,
    account_profile,
)
from job_search_hh.session import SessionPaths, confirm_login


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def _ready_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionPaths:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    set_access_token("fixture-access-token", paths=paths, expires_in=3600)
    return paths


def test_missing_connection_skips_me(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    called = {"n": 0}

    def boom(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        called["n"] += 1
        return 200, {"id": "should-not-run"}, None

    report = account_profile(_paths(tmp_path), me_fetcher=boom)
    assert report["status"] == PROFILE_NOT_AUTHORIZED
    assert report["account"] is None
    assert called["n"] == 0


def test_expired_connection_skips_me(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    set_access_token("expired-token", paths=paths, expires_in=1)
    token_path = paths.state_dir / "hh_token.json"
    payload = json.loads(token_path.read_text(encoding="utf-8"))
    payload["expires_at"] = time.time() - 120
    token_path.write_text(json.dumps(payload), encoding="utf-8")

    called = {"n": 0}

    def boom(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        called["n"] += 1
        return 200, {"id": "x"}, None

    report = account_profile(paths, me_fetcher=boom)
    assert report["status"] == PROFILE_EXPIRED
    assert called["n"] == 0


def test_me_200_normalizes_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return (
            200,
            {
                "id": "hh-user-42",
                "first_name": "Alex",
                "last_name": "Example",
                "email": "alex@example.test",
                "phone": "+70000000000",
                "counters": {"resumes_count": 3},
            },
            None,
        )

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_AVAILABLE
    assert report["connection_status"] == "connected"
    assert report["account"] == {
        "external_id": "hh-user-42",
        "display_name": "Alex Example",
        "email": "alex@example.test",
    }
    blob = json.dumps(report)
    assert "fixture-access-token" not in blob
    assert "phone" not in blob
    assert "resumes_count" not in blob
    assert "+70000000000" not in blob


def test_me_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return 401, None, "http_401"

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_NOT_AUTHORIZED
    assert report["code"] == "me_unauthorized"
    assert report["account"] is None


def test_me_403(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return 403, None, "http_403"

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_PERMISSION_BLOCKED
    assert report["code"] == "me_forbidden"


def test_me_upstream_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return None, None, "upstream_failure"

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_UNAVAILABLE
    assert report["code"] == "me_upstream_failure"


def test_me_malformed_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return 200, None, "invalid_hh_response"

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_UNAVAILABLE
    assert report["code"] == "me_invalid_response"


def test_me_missing_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _ready_session(tmp_path, monkeypatch)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return 200, {"first_name": "Only"}, None

    report = account_profile(paths, me_fetcher=fake_me)
    assert report["status"] == PROFILE_UNAVAILABLE
    assert report["code"] == "me_missing_identity"
