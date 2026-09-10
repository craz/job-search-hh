"""HH CAPTCHA / challenge detection and fail-fast during detail loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.session import SessionPaths, confirm_login
from job_search_hh.vacancy_browser import STATUS_ACTION_REQUIRED, acquire_vacancies
from job_search_hh.vacancy_extractors import (
    extract_detail_page,
    looks_like_hh_challenge,
)
from job_search_hh.vacancy_query import ExecutionPolicy, SearchCriteria


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _FakePage:
    def __init__(self, *, url: str, title: str = "", evaluate_payload: dict[str, Any] | None = None):
        self.url = url
        self._title = title
        self._evaluate_payload = evaluate_payload or {}
        self.evaluate_calls = 0

    def title(self) -> str:
        return self._title

    def evaluate(self, _script: str) -> Any:
        self.evaluate_calls += 1
        # First evaluate is challenge DOM probe; subsequent is DETAIL_EXTRACT_JS.
        if self.evaluate_calls == 1 and "showcaptcha" in (_script or ""):
            return False
        return self._evaluate_payload


def test_looks_like_hh_challenge_url_and_title() -> None:
    assert looks_like_hh_challenge(url="https://hh.ru/account/login?backurl=/showcaptcha")
    assert looks_like_hh_challenge(url="https://hh.ru/captcha?from=vacancy")
    assert looks_like_hh_challenge(url="https://hh.ru/vacancy/1", title="SmartCaptcha")
    assert not looks_like_hh_challenge(
        url="https://hh.ru/vacancy/123456", title="Python developer"
    )


def test_extract_detail_normal_vacancy_page() -> None:
    page = _FakePage(
        url="https://hh.ru/vacancy/123456",
        title="Python developer",
        evaluate_payload={
            "kind": "ok",
            "content": {
                "external_id": "123456",
                "title": "Python developer",
                "description": "Full text",
            },
        },
    )
    payload = extract_detail_page(page)
    assert payload["kind"] == "ok"
    assert payload["content"]["external_id"] == "123456"


def test_extract_detail_challenge_url_fail_fast_without_dom() -> None:
    page = _FakePage(
        url="https://hh.ru/showcaptcha?d=abc",
        title="Attention Required",
        evaluate_payload={"kind": "ok", "content": {"external_id": "1"}},
    )
    payload = extract_detail_page(page)
    assert payload["kind"] == "captcha_or_action_required"
    assert page.evaluate_calls == 0


def test_mid_details_captcha_stops_further_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    progress_phases: list[str] = []

    def reader(**_kwargs: Any) -> dict[str, Any]:
        on_progress = _kwargs.get("on_page_progress")
        pages = [
            {
                "page": 0,
                "status": "ok",
                "url": "https://hh.ru/search/vacancy",
                "items": [
                    {
                        "external_id": "1001",
                        "title": "A",
                        "url": "https://hh.ru/vacancy/1001",
                        "employer_name": "X",
                    },
                    {
                        "external_id": "1002",
                        "title": "B",
                        "url": "https://hh.ru/vacancy/1002",
                        "employer_name": "Y",
                    },
                    {
                        "external_id": "1003",
                        "title": "C",
                        "url": "https://hh.ru/vacancy/1003",
                        "employer_name": "Z",
                    },
                ],
                "meta": {"found_text": "Найдено 3 вакансии"},
            }
        ]
        # Simulate: first detail ok, second hits CAPTCHA — no third detail.
        return {
            "kind": "captcha_or_action_required",
            "pages": pages,
            "details": [
                {
                    "external_id": "1001",
                    "status": "ok",
                    "content": {
                        "external_id": "1001",
                        "title": "A",
                        "description": "ok",
                        "url": "https://hh.ru/vacancy/1001",
                    },
                }
            ],
            "wall_detail_id": "1002",
            "challenge_url": "https://hh.ru/showcaptcha?d=1",
            "challenge_title": "SmartCaptcha",
        }

    # Wire progress via acquire_vacancies on_page_progress through page_reader kwargs —
    # reader above ignores it; call acquire and assert status/code.
    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=1),
        paths=paths,
        page_reader=reader,
        fetch_details=True,
        detail_limit=10,
        on_page_progress=lambda p: progress_phases.append(str(p.get("phase") or "")),
    )
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["code"] == "browser_captcha_or_action_required"
    assert report["action"]["code"] == "confirm_login"
    assert report["challenge_url"] == "https://hh.ru/showcaptcha?d=1"
    assert report["wall_detail_id"] == "1002"
    assert report["recovery"]["kind"] == "captcha_or_action_required"
    # Only the detail completed before the wall is retained.
    assert len(report["details"]) == 1
    assert report["details"][0]["external_id"] == "1001"
    assert report["code"] != "browser_proxy_unavailable"
    assert report["code"] != "vacancy_detail_failed"
