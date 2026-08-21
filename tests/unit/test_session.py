"""Unit tests for session/profile scaffold helpers."""

from pathlib import Path

import pytest

from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    browser_automation_level,
    session_status,
)


def test_session_status_reports_scaffold_without_chromium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HH_CHROMIUM_INSTALLED", raising=False)
    monkeypatch.delenv("HH_NOVNC_ENABLED", raising=False)
    monkeypatch.setattr("job_search_hh.session.shutil.which", lambda _name: None)
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    report = session_status(paths)

    assert report["browser_automation"] == "scaffold"
    assert report["chromium_installed"] is False
    assert report["novnc_configured"] is False
    assert report["profile_lock"] == "unlocked"
    assert report["auth_session"] == "absent"


def test_browser_automation_installed_when_flags_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setenv("HH_NOVNC_ENABLED", "1")
    monkeypatch.setenv("HH_NOVNC_WEB", str(tmp_path))
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    assert browser_automation_level() == "installed"


def test_profile_lock_is_exclusive(tmp_path: Path) -> None:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    paths.ensure()
    lock = ProfileLock(paths.profile_dir)
    lock.acquire("owner-a")
    with pytest.raises(SessionError, match="profile_locked"):
        lock.acquire("owner-b")
    lock.release()
    assert lock.status() == "unlocked"


def test_auth_status_is_not_login_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_CHROMIUM_INSTALLED", raising=False)
    monkeypatch.delenv("HH_NOVNC_ENABLED", raising=False)
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    report = auth_status(paths)
    assert report["login_ready"] is False
    assert report["auth_session"] == "absent"
