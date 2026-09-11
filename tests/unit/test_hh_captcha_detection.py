"""HH CAPTCHA / challenge detection and fail-fast during detail loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.session import SessionPaths, confirm_login
from job_search_hh.vacancy_browser import STATUS_ACTION_REQUIRED, acquire_vacancies
from job_search_hh.vacancy_extractors import (
    challenge_context_confirmed,
    challenge_dom_hit,
    extract_detail_page,
    looks_like_hh_challenge,
)
from job_search_hh.vacancy_query import ExecutionPolicy, SearchCriteria


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _FakePage:
    def __init__(
        self, *, url: str, title: str = "", evaluate_payload: dict[str, Any] | None = None
    ):
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
            return {"hit": False, "signals": []}
        return self._evaluate_payload


def test_looks_like_hh_challenge_url_and_title() -> None:
    assert looks_like_hh_challenge(url="https://hh.ru/account/login?backurl=/showcaptcha")
    assert looks_like_hh_challenge(url="https://hh.ru/captcha?from=vacancy")
    assert looks_like_hh_challenge(url="https://hh.ru/vacancy/1", title="SmartCaptcha")
    assert not looks_like_hh_challenge(url="https://hh.ru/vacancy/123456", title="Python developer")
    # Regression A: vacancy title containing "Robotics" must NOT match.
    assert not looks_like_hh_challenge(
        url="https://hh.ru/vacancy/137205192",
        title="Technical Project Manager — Robotics",
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
    monkeypatch.setattr(
        "job_search_hh.vacancy_browser._finalize_captcha_handoff",
        lambda raw, report, resolved: {
            "action": {"code": "open_challenge", "novnc_url": "http://127.0.0.1:6080/vnc.html"},
            "challenge": {"screenshot_available": True},
        },
    )
    progress_phases: list[str] = []

    def reader(**_kwargs: Any) -> dict[str, Any]:
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
    assert report["action"]["code"] == "open_challenge"
    assert report["challenge_url"] == "https://hh.ru/showcaptcha?d=1"
    assert report["wall_detail_id"] == "1002"
    assert report["recovery"]["kind"] == "captcha_or_action_required"
    # Only the detail completed before the wall is retained.
    assert len(report["details"]) == 1
    assert report["details"][0]["external_id"] == "1001"
    assert report["code"] != "browser_proxy_unavailable"
    assert report["code"] != "vacancy_detail_failed"


# ---------------------------------------------------------------------------
# Evidence consistency regressions (owner A–E)
# ---------------------------------------------------------------------------


def test_regression_a_robotics_title_not_challenge() -> None:
    """A: «Technical Project Manager — Robotics» must not trip URL/title detector."""
    url = "https://hh.ru/vacancy/137205192"
    title = "Technical Project Manager — Robotics"
    assert not looks_like_hh_challenge(url=url, title=title)
    assert not challenge_context_confirmed(url=url, title=title, matched_signals=["dom_title"])


def test_regression_b_real_captcha_title_and_url_still_match() -> None:
    """B: real CAPTCHA URL/title phrases still detect."""
    assert looks_like_hh_challenge(url="https://hh.ru/showcaptcha?d=1", title="")
    assert looks_like_hh_challenge(
        url="https://hh.ru/account/captcha",
        title="Подтвердите, что вы не робот",
    )
    assert challenge_context_confirmed(
        url="https://hh.ru/showcaptcha?d=1",
        title="Подтвердите, что вы не робот",
        matched_signals=["url", "title"],
    )


def test_regression_c_vacancy_capture_is_invalid_not_recoverable(
    tmp_path: Path,
) -> None:
    """C: vacancy page capture → captcha_capture_invalid, recovery unavailable."""
    from job_search_hh.challenge_handoff import (
        CAPTURE_INVALID,
        capture_and_persist_live_challenge,
        public_challenge_view,
        read_challenge_state,
    )

    paths = _paths(tmp_path)

    class _VacancyPage:
        url = "https://hh.ru/vacancy/137205192"

        def title(self) -> str:
            return "Technical Project Manager — Robotics"

        def screenshot(self, **_kwargs: Any) -> None:
            target = _kwargs.get("path")
            if target:
                Path(target).write_bytes(b"\x89PNG_fake")

        def evaluate(self, _script: str) -> Any:
            # Simulate the pre-fix DOM false positive (bare robot → Robotics).
            return {"hit": True, "signals": ["dom_title"]}

    evidence = capture_and_persist_live_challenge(
        _VacancyPage(),
        run_id="run-robotics-fp",
        vacancy_id="137205192",
        paths=paths,
        matched_signals=["dom_title"],
    )
    assert evidence["capture_status"] == CAPTURE_INVALID
    assert evidence["challenge_context_confirmed"] is False
    assert evidence["recovery_available"] is False
    state = read_challenge_state(paths)
    assert state is not None
    assert state["capture_status"] == CAPTURE_INVALID
    assert state["run_id"] == "run-robotics-fp"
    assert state["vacancy_id"] == "137205192"
    assert state["page_identity"]["url"].endswith("/vacancy/137205192")
    # D-partial: Web/API must not expose as active recoverable CAPTCHA.
    assert public_challenge_view(paths) is None


def test_regression_d_public_view_hides_invalid(tmp_path: Path) -> None:
    """D: inconsistent evidence → not normal active recoverable CAPTCHA."""
    from job_search_hh.challenge_handoff import (
        CAPTURE_INVALID,
        public_challenge_view,
        write_challenge_state,
    )

    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/vacancy/137205192",
        challenge_title="Technical Project Manager — Robotics",
        run_id="r1",
        vacancy_id="137205192",
        screenshot={"screenshot_available": True, "screenshot_filename": "x.png"},
        paths=paths,
        matched_signals=["dom_title"],
    )
    state_path = paths.state_dir / "challenge_active.json"
    assert state_path.is_file()
    import json

    disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert disk["capture_status"] == CAPTURE_INVALID
    assert disk["recovery_available"] is False
    assert public_challenge_view(paths) is None


def test_regression_e_real_challenge_still_recoverable(tmp_path: Path) -> None:
    """E: real challenge URL + title still creates recoverable captured state."""
    from job_search_hh.challenge_handoff import (
        CAPTURE_OK,
        capture_and_persist_live_challenge,
        public_challenge_view,
    )

    paths = _paths(tmp_path)

    class _CaptchaPage:
        url = "https://hh.ru/account/captcha?state=1"

        def title(self) -> str:
            return "Подтвердите, что вы не робот"

        def screenshot(self, **_kwargs: Any) -> None:
            target = _kwargs.get("path")
            if target:
                Path(target).write_bytes(b"\x89PNG_fake")

        def evaluate(self, _script: str) -> Any:
            return {"hit": True, "signals": ["dom_url", "dom_title", "dom_body_challenge"]}

    evidence = capture_and_persist_live_challenge(
        _CaptchaPage(),
        run_id="run-real-captcha",
        vacancy_id=None,
        paths=paths,
    )
    assert evidence["capture_status"] == CAPTURE_OK
    assert evidence["challenge_context_confirmed"] is True
    assert evidence["recovery_available"] is True
    view = public_challenge_view(paths)
    assert view is not None
    assert view["recovery_available"] is True
    assert view["run_id"] == "run-real-captcha"
    assert "captcha" in (view.get("challenge_url") or "")


def test_challenge_dom_hit_normalizes_legacy_bool() -> None:
    assert challenge_dom_hit(False) == (False, [])
    assert challenge_dom_hit(True)[0] is True
    hit, signals = challenge_dom_hit({"hit": True, "signals": ["dom_url"]})
    assert hit and signals == ["dom_url"]
