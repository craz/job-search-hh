"""Unit tests for session/profile and operator auth markers."""

from pathlib import Path

import pytest

from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    browser_automation_level,
    clear_login,
    confirm_login,
    open_login,
    session_status,
)


class FakeLauncher:
    def __init__(self) -> None:
        self.calls = 0

    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        self.calls += 1
        assert profile_dir.exists()
        assert "hh.ru" in login_url


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


def test_open_login_and_confirm_mark_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    launcher = FakeLauncher()
    opened = open_login(paths, launcher=launcher)
    assert opened["browser_started"] is True
    assert opened["captcha_bypass"] is False
    assert launcher.calls == 1
    assert auth_status(paths)["login_ready"] is False

    confirmed = confirm_login(paths, confirmed=True)
    assert confirmed["auth_session"] == "present"
    assert confirmed["login_ready"] is True

    cleared = clear_login(paths)
    assert cleared["auth_session"] == "absent"
    assert cleared["login_ready"] is False


def test_confirm_login_stops_detached_browser_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    paths.ensure()
    lock = ProfileLock(paths.profile_dir)
    lock.acquire("login-browser")
    pid_path = paths.state_dir / "login-browser.pid"
    # Non-existent pid: kill is best-effort; lock must still release.
    pid_path.write_text("1", encoding="utf-8")
    confirmed = confirm_login(paths, confirmed=True)
    assert confirmed["login_ready"] is True
    assert not pid_path.exists()
    assert lock.status() == "unlocked"


def test_confirm_requires_explicit_flag(tmp_path: Path) -> None:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    with pytest.raises(SessionError, match="confirmation_required"):
        confirm_login(paths, confirmed=False)


def test_open_login_requires_chromium(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_CHROMIUM_INSTALLED", raising=False)
    monkeypatch.setattr("job_search_hh.session.shutil.which", lambda _name: None)
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    with pytest.raises(SessionError, match="chromium_missing"):
        open_login(paths, launcher=FakeLauncher())
