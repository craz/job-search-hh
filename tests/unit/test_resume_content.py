"""Unit tests for HH browser RO resume detail extract (R2.1.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.resume_content import (
    EXTRACTOR_VERSION,
    STATUS_ACTION_REQUIRED,
    STATUS_AVAILABLE,
    STATUS_NOT_AUTHORIZED,
    STATUS_PERMISSION_BLOCKED,
    STATUS_UNAVAILABLE,
    _scrub_content,
    read_resume_content,
)
from job_search_hh.session import SessionPaths, confirm_login, write_auth_session


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def test_scrub_strips_email_and_phone_from_allowlisted_fields() -> None:
    cleaned = _scrub_content(
        {
            "title": "PM",
            "about": "Reach me at ops@example.com or +7 999 123-45-67 for details",
            "skills": ["Python", "ops@example.com"],
            "experience": [
                {
                    "company": "Acme",
                    "description": "Wrote APIs; email backup@acme.test",
                }
            ],
        }
    )
    assert cleaned["title"] == "PM"
    assert "ops@example.com" not in cleaned["about"]
    assert "+7" not in cleaned["about"]
    assert cleaned["skills"] == ["Python"]
    assert "backup@acme.test" not in cleaned["experience"][0]["description"]


def test_without_browser_login_skips_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    called = {"n": 0}

    def boom(**_kwargs: Any) -> dict[str, Any]:
        called["n"] += 1
        return {"kind": "ok", "content": {"title": "X"}}

    report = read_resume_content("abcdef12", _paths(tmp_path), page_reader=boom)
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["code"] == "browser_login_required"
    assert report["content"] is None
    assert report["action"]["code"] == "open_login"
    assert report["recovery"]["kind"] == "reauth"
    assert called["n"] == 0


def test_invalid_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    report = read_resume_content("ab", _paths(tmp_path), page_reader=lambda **_: {})
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "invalid_resume_id"


def test_login_wall_is_not_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def login_wall(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "login_required", "content": {}}

    report = read_resume_content("abcdef12", paths, page_reader=login_wall)
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["code"] == "browser_session_not_logged_in"
    assert report["content"] is None


def test_profile_locked_offers_confirm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    from job_search_hh.session import ProfileLock

    ProfileLock(paths.profile_dir).acquire("login-browser")

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("reader must not run while locked")

    report = read_resume_content("abcdef12", paths, page_reader=boom)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "profile_locked"
    assert report["action"]["code"] == "confirm_login"


def test_permission_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    write_auth_session(paths, "present", source="test")

    def blocked(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "permission_blocked", "content": {}}

    report = read_resume_content("abcdef12", paths, page_reader=blocked)
    assert report["status"] == STATUS_PERMISSION_BLOCKED
    assert report["content"] is None
    assert report["recovery"]["kind"] == "external_limitation"


def test_captcha_is_action_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def captcha(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "captcha_or_action_required", "content": {}}

    report = read_resume_content("abcdef12", paths, page_reader=captcha)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["code"] == "browser_captcha_or_action_required"
    assert report["action"]["code"] == "confirm_login"


def test_available_content_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    seen: dict[str, Any] = {}

    def ok_reader(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "kind": "ok",
            "content": {
                "title": "Backend Engineer",
                "about": "Build APIs",
                "skills": ["Python", "SQL"],
                "experience": [{"company": "Acme", "position": "Engineer"}],
                "phone": "+79990001122",
                "email": "leak@example.com",
            },
        }

    report = read_resume_content("resumeid99", paths, page_reader=ok_reader)
    assert report["status"] == STATUS_AVAILABLE
    assert report["code"] == "ready"
    assert report["external_resume_id"] == "resumeid99"
    assert report["source"] == "hh"
    assert report["transport"] == "browser_readonly"
    assert report["extractor_version"] == EXTRACTOR_VERSION
    assert report["captured_at"]
    assert report["content"] == {
        "title": "Backend Engineer",
        "about": "Build APIs",
        "skills": ["Python", "SQL"],
        "experience": [{"company": "Acme", "position": "Engineer"}],
    }
    assert "phone" not in report["content"]
    assert "email" not in report["content"]
    assert "resumeid99" in str(seen.get("resume_url"))
    assert report["recovery"]["kind"] == "none"


def test_empty_content_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def empty(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "empty", "content": {}}

    report = read_resume_content("abcdef12", paths, page_reader=empty)
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "resume_content_empty"
    assert report["content"] is None
