"""HH-side R2.1.4: extract/HH failure must not invent or rewrite Core versions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_search_hh.active_resume import write_stored_external_id
from job_search_hh.resume_sync import sync_resume_content
from job_search_hh.session import SessionPaths


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _RecordingCore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_resume_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        raise AssertionError("Core must not be called on HH unavailable")


def test_hh_unavailable_does_not_create_fake_resume_version(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    core = _RecordingCore()
    report = sync_resume_content(
        paths=paths,
        content_reader=lambda *_a, **_k: {
            "status": "unavailable",
            "code": "browser_resume_read_failed",
            "content": None,
            "action": {"code": "none"},
            "recovery": {"kind": "network_failure"},
        },
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["code"] == "browser_resume_read_failed"
    assert report["ingest"] is None
    assert core.calls == []


def test_stale_extract_action_required_skips_core(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    core = _RecordingCore()
    report = sync_resume_content(
        paths=paths,
        content_reader=lambda *_a, **_k: {
            "status": "action_required",
            "code": "browser_captcha_or_action_required",
            "content": None,
            "action": {"code": "confirm_login"},
        },
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["status"] == "action_required"
    assert core.calls == []
