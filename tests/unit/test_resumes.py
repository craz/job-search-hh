"""Unit tests for browser read-only HH resume list (R1.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.resumes import (
    STATUS_AVAILABLE,
    STATUS_NOT_AUTHORIZED,
    STATUS_PERMISSION_BLOCKED,
    STATUS_UNAVAILABLE,
    list_resumes,
    parse_resume_href,
)
from job_search_hh.session import SessionPaths, confirm_login, write_auth_session


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def test_parse_resume_href() -> None:
    assert parse_resume_href("https://hh.ru/resume/abcdef12") == "abcdef12"
    assert parse_resume_href("/resume/short") is None


def test_without_browser_login_skips_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    called = {"n": 0}

    def boom(**_kwargs: Any) -> dict[str, Any]:
        called["n"] += 1
        return {"kind": "ok", "items": []}

    report = list_resumes(_paths(tmp_path), page_reader=boom)
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["code"] == "browser_login_required"
    assert report["items"] == []
    assert report["action"]["code"] == "open_login"
    assert called["n"] == 0


def test_login_wall_is_not_empty_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def login_wall(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "login_required", "items": []}

    report = list_resumes(paths, page_reader=login_wall)
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["code"] == "browser_session_not_logged_in"
    assert report["items"] == []
    assert report["action"]["code"] == "open_login"


def test_permission_blocked_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    write_auth_session(paths, "present", source="test")

    def blocked(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "permission_blocked", "items": []}

    report = list_resumes(paths, page_reader=blocked)
    assert report["status"] == STATUS_PERMISSION_BLOCKED
    assert report["items"] == []


def test_available_list_normalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def ok(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "items": [
                {"external_id": "resumehash01", "title": "  Product Manager  "},
                {"external_id": "resumehash01", "title": "dup"},
                {"external_id": "x", "title": "too-short-id"},
                {"external_id": "resumehash02", "title": "Engineer"},
            ],
        }

    report = list_resumes(paths, page_reader=ok)
    assert report["status"] == STATUS_AVAILABLE
    assert report["code"] == "ready"
    assert report["transport"] == "browser_readonly"
    assert report["items"] == [
        {"external_id": "resumehash01", "title": "Product Manager"},
        {"external_id": "resumehash02", "title": "Engineer"},
    ]


def test_empty_authorized_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def empty(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "ok", "items": []}

    report = list_resumes(paths, page_reader=empty)
    assert report["status"] == STATUS_AVAILABLE
    assert report["code"] == "empty"
    assert report["items"] == []


def test_reader_failure_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("browser crash")

    report = list_resumes(paths, page_reader=boom)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "browser_resume_read_failed"
    assert report["items"] == []
