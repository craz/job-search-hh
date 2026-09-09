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
    assert not lock.is_symlink()
    assert not (profile / "SingletonCookie").exists()
    assert not (profile / "SingletonCookie").is_symlink()
    assert not (profile / "SingletonSocket").exists()
    assert not (profile / "SingletonSocket").is_symlink()


def test_clear_stale_removes_dangling_symlinks_when_exists_is_false(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to("missing-target-xyz")
    assert lock.exists() is False
    assert lock.is_symlink() is True
    _clear_stale_chromium_singleton(profile)
    assert not lock.is_symlink()


def test_clear_stale_requires_same_process_line(tmp_path: Path, monkeypatch) -> None:
    """Profile path on one ps line and chrome on another must not block cleanup."""
    from job_search_hh import browser as browser_mod

    profile = tmp_path / "profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to("dead-host-123")

    class Result:
        stdout = f"python helper {profile}\n/usr/bin/unrelated-chrome-helper\n"

    monkeypatch.setattr(
        browser_mod.subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )
    _clear_stale_chromium_singleton(profile)
    assert not lock.exists()
