"""Unit tests for HH vacancy source-status check (R2.4.1b)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.session import SessionPaths, confirm_login
from job_search_hh.vacancy_browser import (
    STATUS_AVAILABLE,
    STATUS_NOT_AUTHORIZED,
    STATUS_UNAVAILABLE,
)
from job_search_hh.vacancy_source_status import (
    VacancySourceStatusResult,
    check_vacancy_source_status,
)


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def _ok_detail(*, external_id: str, archived: bool) -> dict[str, Any]:
    return {
        "kind": "ok",
        "content": {
            "external_id": external_id,
            "title": "Python developer",
            "url": f"https://hh.ru/vacancy/{external_id}",
            "archived": archived,
        },
    }


def test_vacancy_source_status_result_shape() -> None:
    result = VacancySourceStatusResult(
        external_id="1001",
        status="active",
        checked_at="2026-01-01T00:00:00Z",
        evidence=None,
        reason=None,
        transport_status=STATUS_AVAILABLE,
    )
    assert result.status == "active"
    assert result.evidence is None


def test_a_active_vacancy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    report = check_vacancy_source_status(
        "1001",
        paths,
        page_reader=lambda **_: _ok_detail(external_id="1001", archived=False),
    )
    assert report["external_id"] == "1001"
    assert report["status"] == "active"
    assert report["transport_status"] == STATUS_AVAILABLE
    assert report["evidence"] is None
    assert report["reason"] is None
    assert report["hh_writes"] is False
    assert report["core_writes"] is False
    assert report["code"] == "ready"
    assert report["recovery"]["kind"] == "none"


def test_b_archived_vacancy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    report = check_vacancy_source_status(
        "2002",
        paths,
        page_reader=lambda **_: _ok_detail(external_id="2002", archived=True),
    )
    assert report["status"] == "archived"
    assert report["transport_status"] == STATUS_AVAILABLE
    assert report["evidence"] is not None
    assert "data-qa=vacancy-archived" in report["evidence"]
    assert "archive" in report["evidence"].lower()
    assert report["reason"] is None
    assert report["core_writes"] is False


def test_c_transport_error_is_unknown_not_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated network failure")

    report = check_vacancy_source_status("3003", paths, page_reader=boom)
    assert report["status"] == "unknown"
    assert report["status"] != "archived"
    assert report["transport_status"] == STATUS_UNAVAILABLE
    assert report["evidence"] is None
    assert report["reason"] == "browser_vacancy_read_failed"
    assert report["core_writes"] is False
    assert report["hh_writes"] is False


def test_auth_wall_is_unknown_not_archived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    report = check_vacancy_source_status(
        "4004",
        paths,
        page_reader=lambda **_: {"kind": "login_required", "content": None},
    )
    assert report["status"] == "unknown"
    assert report["transport_status"] == STATUS_NOT_AUTHORIZED
    assert report["evidence"] is None


def test_without_login_skips_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    called = {"n": 0}

    def boom(**_kwargs: Any) -> dict[str, Any]:
        called["n"] += 1
        return _ok_detail(external_id="1001", archived=True)

    report = check_vacancy_source_status("1001", _paths(tmp_path), page_reader=boom)
    assert report["status"] == "unknown"
    assert report["transport_status"] == STATUS_NOT_AUTHORIZED
    assert called["n"] == 0


def test_invalid_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    report = check_vacancy_source_status(
        "not-a-digit",
        _paths(tmp_path),
        page_reader=lambda **_: _ok_detail(external_id="1", archived=True),
    )
    assert report["status"] == "unknown"
    assert report["code"] == "invalid_vacancy_id"
