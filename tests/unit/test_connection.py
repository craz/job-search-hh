"""Unit tests for product-facing HH connection status mapping."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from job_search_hh.connection import (
    STATUS_ACTION_REQUIRED,
    STATUS_CONNECTED,
    STATUS_EXPIRED,
    STATUS_NOT_AUTHORIZED,
    STATUS_UNAVAILABLE,
    connection_status,
)
from job_search_hh.oauth import set_access_token
from job_search_hh.session import SessionPaths, confirm_login, write_auth_session


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def test_missing_session_is_not_authorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    report = connection_status(paths)
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["authenticated"] is False
    assert report["action"]["code"] == "open_login"
    assert "access_token" not in json.dumps(report)


def test_valid_session_is_connected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    set_access_token("fixture-access-token", paths=paths, expires_in=3600)
    report = connection_status(paths)
    assert report["status"] == STATUS_CONNECTED
    assert report["authenticated"] is True
    assert report["login_ready"] is True
    assert report["expired"] is False
    assert report["action"]["code"] == "none"
    assert report["code"] == "ready"
    assert report["recovery"]["kind"] == "none"
    blob = json.dumps(report)
    assert "fixture-access-token" not in blob


def test_expired_token_is_session_expired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    set_access_token("expired-token", paths=paths, expires_in=1)
    # Force expiry without waiting the wall clock past the 60s refresh skew.
    token_path = paths.state_dir / "hh_token.json"
    payload = json.loads(token_path.read_text(encoding="utf-8"))
    payload["expires_at"] = time.time() - 120
    token_path.write_text(json.dumps(payload), encoding="utf-8")
    report = connection_status(paths)
    assert report["status"] == STATUS_EXPIRED
    assert report["expired"] is True
    assert report["action"]["code"] == "reconnect"
    assert report["recovery"]["kind"] == "reauth"
    assert "expired-token" not in json.dumps(report)


def test_pending_operator_is_action_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    write_auth_session(paths, "pending_operator", source="test")
    report = connection_status(paths)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["code"] == "operator_confirm_required"
    assert report["action"]["code"] == "confirm_login"


def test_login_ready_without_token_is_action_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    report = connection_status(paths)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["code"] == "access_token_missing"
    assert report["action"]["code"] == "acquire_token"


def test_invalid_session_marker_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    paths.ensure()
    paths.session_marker.write_text("{not-json", encoding="utf-8")
    report = connection_status(paths)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "session_marker_invalid"


def test_present_without_chromium_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HH_CHROMIUM_INSTALLED", raising=False)
    monkeypatch.setattr("job_search_hh.session.shutil.which", lambda _name: None)
    paths = _paths(tmp_path)
    write_auth_session(paths, "present", source="test")
    report = connection_status(paths)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "login_runtime_unavailable"


def test_connection_read_failure_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)

    def boom(_paths: SessionPaths | None = None) -> dict[str, object]:
        raise OSError("fixture disk failure")

    monkeypatch.setattr("job_search_hh.connection.auth_status", boom)
    report = connection_status(paths)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "connection_read_failed"
    assert report["detail"] == "OSError"
