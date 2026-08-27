"""Unit tests for manual HH → Core resume content sync (R2.1.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_search_hh.active_resume import write_stored_external_id
from job_search_hh.core_client import CoreError
from job_search_hh.resume_sync import sync_resume_content
from job_search_hh.session import SessionPaths


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _FakeCore:
    def __init__(self, *, fail: bool = False, created: bool = True) -> None:
        self.fail = fail
        self.created = created
        self.calls: list[dict[str, Any]] = []

    def create_resume_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        if self.fail:
            raise CoreError("core_down")
        return {
            "created": self.created,
            "resume_version": {
                "id": "00000000-0000-0000-0000-000000000099",
                "content_hash": "abc123",
                "external_resume_id": payload["external_resume_id"],
                "source": "hh",
            },
            "candidate_context": {
                "resume_content": {
                    "content_state": "synced",
                    "resume_version_id": "00000000-0000-0000-0000-000000000099",
                    "external_resume_id": payload["external_resume_id"],
                }
            },
        }


def test_no_active_resume_does_not_call_core(tmp_path: Path) -> None:
    core = _FakeCore()
    report = sync_resume_content(
        paths=_paths(tmp_path),
        content_reader=lambda *_a, **_k: {"status": "available", "content": {"title": "X"}},
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["code"] == "no_active_resume"
    assert report["recovery"]["kind"] != "none" or report["action"]["code"] == "select_resume"
    assert core.calls == []


def test_extract_failure_skips_core(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    core = _FakeCore()
    report = sync_resume_content(
        paths=paths,
        content_reader=lambda *_a, **_k: {
            "status": "not_authorized",
            "code": "browser_login_required",
            "content": None,
            "action": {"code": "open_login"},
            "recovery": {"kind": "reauth"},
        },
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["status"] == "not_authorized"
    assert report["code"] == "browser_login_required"
    assert report["ingest"] is None
    assert core.calls == []


def test_successful_sync_creates_version(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    core = _FakeCore(created=True)

    def reader(external_id: str, *_a: Any, **_k: Any) -> dict[str, Any]:
        assert external_id == "resumehash01"
        return {
            "status": "available",
            "code": "ready",
            "content": {"title": "PM", "skills": ["Python"]},
            "transport": "browser_readonly",
            "extractor_version": "hh-browser-ro-v1",
            "captured_at": "2026-08-27T12:00:00Z",
        }

    report = sync_resume_content(
        paths=paths,
        content_reader=reader,
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is True
    assert report["code"] == "synced"
    assert report["ingest"]["created"] is True
    assert report["ingest"]["resume_version_id"] == "00000000-0000-0000-0000-000000000099"
    assert core.calls[0]["external_resume_id"] == "resumehash01"
    assert core.calls[0]["transport"] == "browser_readonly"
    assert "phone" not in core.calls[0]["content"]
    assert report["candidate_context"]["resume_content"]["content_state"] == "synced"


def test_unchanged_sync_reports_dedup(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    core = _FakeCore(created=False)
    report = sync_resume_content(
        paths=paths,
        content_reader=lambda *_a, **_k: {
            "status": "available",
            "content": {"title": "PM"},
            "transport": "browser_readonly",
            "extractor_version": "hh-browser-ro-v1",
            "captured_at": "2026-08-27T12:00:00Z",
        },
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is True
    assert report["code"] == "unchanged"
    assert report["ingest"]["created"] is False


def test_core_failure_after_extract(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    report = sync_resume_content(
        paths=paths,
        content_reader=lambda *_a, **_k: {
            "status": "available",
            "content": {"title": "PM"},
            "transport": "browser_readonly",
            "captured_at": "2026-08-27T12:00:00Z",
        },
        core=_FakeCore(fail=True),  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["code"] == "core_ingest_failed"
    assert report["ingest"]["ok"] is False


def test_explicit_id_overrides_active(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "active-id")
    core = _FakeCore()
    report = sync_resume_content(
        external_resume_id="other-id-99",
        paths=paths,
        content_reader=lambda external_id, *_a, **_k: {
            "status": "available",
            "content": {"title": external_id},
            "transport": "browser_readonly",
            "captured_at": "2026-08-27T12:00:00Z",
        },
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is True
    assert report["external_resume_id"] == "other-id-99"
    assert core.calls[0]["external_resume_id"] == "other-id-99"
