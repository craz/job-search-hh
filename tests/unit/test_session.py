"""Unit tests for session/profile scaffold helpers."""

from pathlib import Path

import pytest

from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    session_status,
)


def test_session_status_reports_scaffold_without_chromium(tmp_path: Path) -> None:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    report = session_status(paths)

    assert report["browser_automation"] == "scaffold"
    assert report["chromium_installed"] is False
    assert report["profile_lock"] == "unlocked"
    assert report["auth_session"] == "absent"


def test_profile_lock_is_exclusive(tmp_path: Path) -> None:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    paths.ensure()
    lock = ProfileLock(paths.profile_dir)
    lock.acquire("owner-a")
    with pytest.raises(SessionError, match="profile_locked"):
        lock.acquire("owner-b")
    lock.release()
    assert lock.status() == "unlocked"


def test_auth_status_is_not_login_ready(tmp_path: Path) -> None:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    report = auth_status(paths)
    assert report["login_ready"] is False
    assert report["auth_session"] == "absent"
