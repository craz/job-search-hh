"""Unit tests for authenticated HH GET provider and live auth gates."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from job_search_hh.live_auth import LiveAuthError, require_authenticated_read
from job_search_hh.providers import AuthenticatedHhApi, ProviderError
from job_search_hh.session import SessionPaths, confirm_login


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_require_authenticated_read_needs_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    with pytest.raises(LiveAuthError, match="login_not_ready"):
        require_authenticated_read(paths)


def test_require_authenticated_read_needs_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.delenv("JOB_SEARCH_HH_ACCESS_TOKEN", raising=False)
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    confirm_login(paths, confirmed=True)
    with pytest.raises(LiveAuthError, match="access_token_missing"):
        require_authenticated_read(paths)


def test_authenticated_api_lists_negotiations(monkeypatch: pytest.MonkeyPatch) -> None:
    negotiations = {
        "items": [
            {
                "id": "n1",
                "state": {"id": "response"},
                "vacancy": {"id": "1001"},
                "created_at": "2026-08-21T12:00:00+00:00",
            }
        ],
        "page": 0,
        "pages": 1,
    }
    resumes = {
        "items": [
            {"id": "r1", "title": "Backend", "views_count": 42, "new_views_count": 3},
            {"id": "r2", "title": "DevOps", "views_count": 8, "new_views_count": 1},
        ]
    }

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:  # noqa: ARG001
        assert request.get_method() == "GET"
        url = request.full_url
        if "/resumes/mine" in url:
            return _FakeResponse(json.dumps(resumes).encode("utf-8"))
        assert "/negotiations" in url
        return _FakeResponse(json.dumps(negotiations).encode("utf-8"))

    monkeypatch.setattr("job_search_hh.providers.urllib.request.urlopen", fake_urlopen)
    api = AuthenticatedHhApi("https://api.hh.ru", "ua", 5.0, "secret-token")
    items = api.list_applications()
    assert items[0]["id"] == "n1"
    assert items[0]["state"] == "response"
    metrics = api.list_metrics()
    assert metrics[0]["applications"] == 1
    assert metrics[0]["replies"] == 1
    assert metrics[0]["views_total"] == 50
    assert metrics[0]["views_new"] == 4
    assert metrics[0]["notes"] == "negotiations_get+resumes_mine"
    assert "secret-token" not in json.dumps(metrics)


def test_metrics_tolerate_resumes_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    negotiations = {
        "items": [{"id": "n1", "state": {"id": "response"}, "vacancy": {"id": "1"}}],
        "page": 0,
        "pages": 1,
    }

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:  # noqa: ARG001
        if "/resumes/mine" in request.full_url:
            raise HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)  # type: ignore[arg-type]
        return _FakeResponse(json.dumps(negotiations).encode("utf-8"))

    monkeypatch.setattr("job_search_hh.providers.urllib.request.urlopen", fake_urlopen)
    api = AuthenticatedHhApi("https://api.hh.ru", "ua", 5.0, "secret-token")
    metrics = api.list_metrics()
    assert "views_total" not in metrics[0]
    assert metrics[0]["notes"] == "negotiations_get+resumes_mine_forbidden"


def test_authenticated_api_rejects_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float = 0) -> Any:  # noqa: ARG001
        raise HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)  # type: ignore[arg-type]

    monkeypatch.setattr("job_search_hh.providers.urllib.request.urlopen", fake_urlopen)
    api = AuthenticatedHhApi("https://api.hh.ru", "ua", 5.0, "secret-token")
    with pytest.raises(ProviderError, match="http_403"):
        api.list_applications()
