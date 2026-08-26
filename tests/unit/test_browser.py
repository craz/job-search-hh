"""Unit tests for headed Chromium launch helpers."""

from __future__ import annotations

from pathlib import Path

from job_search_hh.browser import _clear_stale_chromium_singleton


def test_clear_stale_chromium_singleton_removes_orphan_lock(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to("dead-host-123")
    (profile / "SingletonCookie").symlink_to("cookie")
    (profile / "SingletonSocket").symlink_to("/tmp/missing-socket")

    _clear_stale_chromium_singleton(profile)

    assert not lock.exists()
    assert not (profile / "SingletonCookie").exists()
    assert not (profile / "SingletonSocket").exists()
