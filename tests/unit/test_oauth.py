"""Unit tests for OAuth authorize URL, exchange and private token storage."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from job_search_hh.oauth import (
    OAuthError,
    OAuthSettings,
    build_authorize_url,
    clear_token_record,
    exchange_authorization_code,
    set_access_token,
    token_status,
)
from job_search_hh.session import SessionPaths


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_build_authorize_url_omits_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_SEARCH_HH_CLIENT_ID", "cid")
    monkeypatch.setenv("JOB_SEARCH_HH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("JOB_SEARCH_HH_REDIRECT_URI", "http://127.0.0.1:8765/oauth/callback")
    report = build_authorize_url()
    assert "client_id=cid" in report["authorize_url"]
    assert "csecret" not in json.dumps(report)
    assert report["client_secret_present"] is True


def test_set_and_clear_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HH_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.delenv("JOB_SEARCH_HH_ACCESS_TOKEN", raising=False)
    paths = SessionPaths.from_env()
    stored = set_access_token("tok-123", paths=paths, expires_in=3600)
    assert stored["access_token_present"] is True
    assert "tok-123" not in json.dumps(stored)
    status = token_status(paths)
    assert status["source"] == "token_file"
    assert status["expired"] is False
    cleared = clear_token_record(paths)
    assert cleared["access_token_present"] is False
    assert token_status(paths)["access_token_present"] is False


def test_exchange_authorization_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HH_PROFILE_DIR", str(tmp_path / "profile"))
    settings = OAuthSettings(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://127.0.0.1:8765/oauth/callback",
        auth_host="https://hh.ru",
        user_agent="ua",
        timeout_seconds=5.0,
    )

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:  # noqa: ARG001
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/oauth/token")
        body = request.data.decode("utf-8")
        assert "grant_type=authorization_code" in body
        assert "code=abc" in body
        assert "csecret" in body
        payload = {
            "access_token": "exchanged-token",
            "refresh_token": "refresh-1",
            "expires_in": 1200,
            "token_type": "bearer",
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("job_search_hh.oauth.urllib.request.urlopen", fake_urlopen)
    report = exchange_authorization_code("abc", settings=settings)
    assert report["stored"] is True
    assert report["access_token_present"] is True
    assert "exchanged-token" not in json.dumps(report)


def test_exchange_requires_code() -> None:
    with pytest.raises(OAuthError, match="authorization_code_missing"):
        exchange_authorization_code("  ")
