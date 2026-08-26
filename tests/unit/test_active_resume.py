"""Unit tests for R1.4 active HH resume selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.active_resume import (
    SELECTION_ACTIVE,
    SELECTION_NONE,
    SELECTION_STALE,
    SELECTION_UNAVAILABLE,
    attach_selection,
    read_stored_external_id,
    set_active_resume,
    write_stored_external_id,
)
from job_search_hh.resumes import STATUS_AVAILABLE, STATUS_NOT_AUTHORIZED, list_resumes
from job_search_hh.session import SessionPaths, confirm_login


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def _available_list() -> dict[str, Any]:
    return {
        "status": STATUS_AVAILABLE,
        "items": [
            {"external_id": "resumehash01", "title": "Product Manager"},
            {"external_id": "resumehash02", "title": "Engineer"},
        ],
        "code": "ready",
        "transport": "browser_readonly",
        "action": {"code": "none"},
    }


def test_no_active_selection_by_default(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    report = attach_selection(_available_list(), paths)
    assert report["selection"]["status"] == SELECTION_NONE
    assert report["active_resume"] is None
    assert all(item["active"] is False for item in report["items"])


def test_select_and_mark_active(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = set_active_resume(paths, "resumehash02", list_report=_available_list())
    assert result["ok"] is True
    report = result["resumes"]
    assert report["selection"]["status"] == SELECTION_ACTIVE
    assert report["active_resume"] == {"external_id": "resumehash02", "title": "Engineer"}
    assert [item["active"] for item in report["items"]] == [False, True]
    assert read_stored_external_id(paths) == "resumehash02"


def test_switch_active_resume(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    set_active_resume(paths, "resumehash01", list_report=_available_list())
    result = set_active_resume(paths, "resumehash02", list_report=_available_list())
    assert result["ok"] is True
    assert result["resumes"]["active_resume"]["external_id"] == "resumehash02"
    assert [item["active"] for item in result["resumes"]["items"]] == [False, True]


def test_clear_to_explicit_none(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    set_active_resume(paths, "resumehash01", list_report=_available_list())
    result = set_active_resume(paths, None, list_report=_available_list())
    assert result["ok"] is True
    assert result["code"] == "cleared"
    assert result["resumes"]["selection"]["status"] == SELECTION_NONE
    assert result["resumes"]["active_resume"] is None
    assert read_stored_external_id(paths) is None


def test_invalid_external_id_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = set_active_resume(paths, "missing-resume-id", list_report=_available_list())
    assert result["ok"] is False
    assert result["code"] == "invalid_resume_id"
    assert read_stored_external_id(paths) is None


def test_selection_unavailable_when_list_not_authorized(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "resumehash01")
    unavailable = {
        "status": STATUS_NOT_AUTHORIZED,
        "items": [],
        "code": "browser_session_not_logged_in",
        "action": {"code": "open_login"},
    }
    report = attach_selection(unavailable, paths)
    assert report["selection"]["status"] == SELECTION_UNAVAILABLE
    assert report["selection"]["external_id"] == "resumehash01"
    assert report["active_resume"] is None
    result = set_active_resume(paths, "resumehash01", list_report=unavailable)
    assert result["ok"] is False
    assert result["code"] == "selection_unavailable"


def test_stale_selection_when_id_missing_from_list(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_stored_external_id(paths, "gone-resume-xyz")
    report = attach_selection(_available_list(), paths)
    assert report["selection"]["status"] == SELECTION_STALE
    assert report["selection"]["external_id"] == "gone-resume-xyz"
    assert report["selection"]["action"]["code"] == "reselect"
    assert report["active_resume"] is None
    assert all(item["active"] is False for item in report["items"])


def test_selection_survives_reload_via_state_file(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    set_active_resume(paths, "resumehash01", list_report=_available_list())
    # Simulate restart: new SessionPaths on same dirs.
    restored = SessionPaths(state_dir=paths.state_dir, profile_dir=paths.profile_dir)
    report = attach_selection(_available_list(), restored)
    assert report["selection"]["status"] == SELECTION_ACTIVE
    assert report["active_resume"]["external_id"] == "resumehash01"


def test_list_resumes_includes_selection_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    write_stored_external_id(paths, "resumehash01")

    def ok(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "items": [
                {"external_id": "resumehash01", "title": "Product Manager"},
                {"external_id": "resumehash02", "title": "Engineer"},
            ],
        }

    report = list_resumes(paths, page_reader=ok)
    assert report["items"][0]["active"] is True
    assert report["items"][1]["active"] is False
    assert report["selection"]["status"] == SELECTION_ACTIVE
    assert "cookie" not in str(report).casefold()
    assert "access_token" not in str(report).casefold()


def test_single_resume_is_not_auto_selected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    report = attach_selection(
        {
            "status": STATUS_AVAILABLE,
            "items": [{"external_id": "onlyresume01", "title": "Only One"}],
            "code": "ready",
        },
        paths,
    )
    assert report["selection"]["status"] == SELECTION_NONE
    assert report["items"][0]["active"] is False
