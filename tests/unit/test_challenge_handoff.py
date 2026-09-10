"""Unit tests for CAPTCHA challenge evidence + operator handoff."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from job_search_hh.challenge_handoff import (
    ACTION_CHALLENGE_CAPTURE_FAILED,
    ACTION_OPEN_CHALLENGE,
    CAPTURE_FAILED,
    CAPTURE_NO_SCREENSHOT,
    CAPTURE_OK,
    begin_challenge_handoff,
    captcha_tg_configured,
    capture_and_persist_live_challenge,
    capture_challenge_screenshot,
    clear_challenge_state,
    confirm_challenge_cleared,
    notify_challenge_telegram,
    open_challenge_browser,
    public_challenge_view,
    read_challenge_state,
    write_challenge_state,
    _confirm_probe_urls,
)
from job_search_hh.session import SessionError, SessionPaths, confirm_login
from job_search_hh.vacancy_browser import STATUS_ACTION_REQUIRED, acquire_vacancies
from job_search_hh.vacancy_query import ExecutionPolicy, SearchCriteria


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _ShotPage:
    def __init__(
        self, *, url: str = "https://hh.ru/showcaptcha?d=1", title: str = "SmartCaptcha"
    ) -> None:
        self.called = False
        self.url = url
        self._title = title

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        self.called = True
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def title(self) -> str:
        return self._title


class _FailShotPage(_ShotPage):
    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        raise RuntimeError("shot_boom")


def test_capture_screenshot_from_challenged_page(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    page = _ShotPage()
    shot = capture_challenge_screenshot(page, paths=paths)
    assert page.called is True
    assert shot["screenshot_available"] is True
    assert (paths.state_dir / "challenges" / shot["screenshot_filename"]).is_file()


def test_capture_and_persist_before_close_writes_url_and_shot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    page = _ShotPage(url="https://hh.ru/showcaptcha?d=live")
    evidence = capture_and_persist_live_challenge(
        page,
        vacancy_id="1002",
        progress={"pages_fetched": 5, "checked_count": 250, "phase": "captcha_required"},
        paths=paths,
    )
    assert page.called is True
    assert evidence["challenge_url"].endswith("showcaptcha?d=live")
    assert evidence["screenshot"]["screenshot_available"] is True
    assert evidence["recovery_available"] is True
    assert evidence["capture_status"] == CAPTURE_OK
    state = read_challenge_state(paths)
    assert state is not None
    assert state["challenge_url"].endswith("showcaptcha?d=live")
    assert state["screenshot_available"] is True
    assert (paths.state_dir / "challenges" / state["screenshot_filename"]).is_file()


def test_capture_class_b_url_without_screenshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    page = _FailShotPage(url="https://hh.ru/showcaptcha?d=b")
    evidence = capture_and_persist_live_challenge(page, paths=paths)
    assert evidence["recovery_available"] is True
    assert evidence["capture_status"] == CAPTURE_NO_SCREENSHOT
    assert evidence["screenshot"]["screenshot_error"] == "RuntimeError"
    state = read_challenge_state(paths)
    assert state is not None
    assert state["challenge_url"].endswith("showcaptcha?d=b")
    assert state["screenshot_available"] is False


def test_capture_class_c_missing_url_no_recovery(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    page = _ShotPage(url="")
    evidence = capture_and_persist_live_challenge(page, paths=paths)
    assert evidence["challenge_url"] == ""
    assert evidence["recovery_available"] is False
    assert evidence["capture_status"] == CAPTURE_FAILED
    view = public_challenge_view(paths)
    assert view is not None
    assert view["recovery_available"] is False
    assert view["challenge_url"] is None
    assert view["novnc_url"] is None


def test_telegram_notify_skipped_when_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HH_CAPTCHA_TG", raising=False)
    monkeypatch.delenv("TELEGRAM_DM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_DM_CHAT_ID", raising=False)
    assert captcha_tg_configured() is False
    state = write_challenge_state(
        challenge_url="https://hh.ru/showcaptcha?d=1",
        paths=_paths(tmp_path),
        screenshot={"screenshot_available": True, "screenshot_filename": "x.png"},
    )
    result = notify_challenge_telegram(state)
    assert result["notified"] is False
    assert result["reason"] == "telegram_not_configured"


def test_begin_handoff_persists_operator_state_without_login_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setenv("HH_CAPTCHA_TG", "0")
    monkeypatch.setattr("job_search_hh.challenge_handoff.interactive_display_ready", lambda: False)
    monkeypatch.setattr("job_search_hh.challenge_handoff.novnc_configured", lambda: False)
    report = begin_challenge_handoff(
        challenge_url="https://hh.ru/showcaptcha?d=abc",
        challenge_title="SmartCaptcha",
        vacancy_id="1002",
        progress={"pages_fetched": 5, "pages_planned": 5, "checked_count": 250},
        screenshot={"screenshot_available": True, "screenshot_filename": "cap.png"},
        paths=paths,
        auto_open_browser=False,
    )
    assert report["action"]["code"] == ACTION_OPEN_CHALLENGE
    assert report["action"]["code"] != "open_login"
    assert report["action"]["code"] != "confirm_login"
    assert report["recovery_available"] is True
    state = read_challenge_state(paths)
    assert state is not None
    assert state["status"] == "operator_action_required"
    assert state["challenge_url"].endswith("showcaptcha?d=abc")
    view = public_challenge_view(paths)
    assert view is not None
    assert "screenshot_path" not in view
    assert view["screenshot_available"] is True


def test_begin_handoff_missing_url_is_capture_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setenv("HH_CAPTCHA_TG", "0")
    report = begin_challenge_handoff(
        challenge_url="",
        screenshot={"screenshot_available": False, "screenshot_error": "Empty"},
        paths=paths,
        auto_open_browser=False,
    )
    assert report["action"]["code"] == ACTION_CHALLENGE_CAPTURE_FAILED
    assert report["recovery_available"] is False
    assert report["action"]["novnc_url"] is None


def test_open_challenge_chromium_exit_not_interactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/showcaptcha?d=1",
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.require_interactive_login_runtime", lambda: None
    )
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )

    class _DeadChild:
        pid = 4242

        def poll(self) -> int:
            return 1

        def terminate(self) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.subprocess.Popen",
        lambda *a, **k: _DeadChild(),
    )
    with pytest.raises(SessionError, match="browser_launch_failed"):
        open_challenge_browser(paths=paths)


def test_open_challenge_alive_sets_interactive_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/showcaptcha?d=1",
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.require_interactive_login_runtime", lambda: None
    )
    monkeypatch.setattr("job_search_hh.challenge_handoff.interactive_display_ready", lambda: True)
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.novnc_public_url",
        lambda: "http://127.0.0.1:6080/vnc.html",
    )
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )
    monkeypatch.setattr("job_search_hh.challenge_handoff.time.sleep", lambda *_a, **_k: None)

    class _AliveChild:
        pid = 7777

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.subprocess.Popen",
        lambda *a, **k: _AliveChild(),
    )
    report = open_challenge_browser(paths=paths)
    assert report["browser_started"] is True
    assert report["interactive_ready"] is True
    assert report["ok"] is True


def test_confirm_clears_only_when_challenge_gone(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/showcaptcha",
        paths=paths,
        screenshot={"screenshot_available": False},
    )
    assert read_challenge_state(paths) is not None
    clear_challenge_state(paths)
    assert read_challenge_state(paths) is None
    result = confirm_challenge_cleared(paths)
    assert result["ok"] is True
    assert result["cleared"] is True
    assert result["code"] == "no_active_challenge"


def test_acquire_captcha_uses_open_challenge_not_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    monkeypatch.setattr(
        "job_search_hh.vacancy_browser._finalize_captcha_handoff",
        lambda raw, report, resolved: {
            "action": {
                "code": "open_challenge",
                "novnc_url": "http://127.0.0.1:6080/vnc.html",
                "challenge_url": raw.get("challenge_url"),
            },
            "challenge": {
                "screenshot_available": True,
                "challenge_session_available": False,
                "challenge_url": raw.get("challenge_url"),
                "recovery_available": True,
            },
            "recovery_available": True,
        },
    )

    def captcha(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "captcha_or_action_required",
            "pages": [],
            "details": [],
            "challenge_url": "https://hh.ru/showcaptcha?d=1",
            "screenshot": {"screenshot_available": True, "screenshot_filename": "a.png"},
        }

    report = acquire_vacancies(SearchCriteria(text="python"), paths=paths, page_reader=captcha)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["action"]["code"] == "open_challenge"
    assert report["action"]["code"] != "open_login"
    assert report["action"]["code"] != "confirm_login"
    assert report["screenshot_available"] is True


def test_acquire_does_not_fabricate_challenge_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    monkeypatch.setenv("HH_CAPTCHA_TG", "0")

    def captcha(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "captcha_or_action_required",
            "pages": [],
            "details": [],
            "challenge_url": "",
            "screenshot": {"screenshot_available": False, "screenshot_error": "gone"},
        }

    report = acquire_vacancies(SearchCriteria(text="python"), paths=paths, page_reader=captcha)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["action"]["code"] == ACTION_CHALLENGE_CAPTURE_FAILED
    assert report.get("challenge_url") in {None, ""}
    assert report["recovery_available"] is False
    state = read_challenge_state(paths)
    assert state is not None
    assert state["capture_status"] == CAPTURE_FAILED


def test_mid_details_captcha_stops_and_handoff_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    monkeypatch.setattr(
        "job_search_hh.vacancy_browser._finalize_captcha_handoff",
        lambda raw, report, resolved: {
            "action": {"code": "open_challenge", "novnc_url": "http://127.0.0.1:6080/vnc.html"},
            "challenge": {
                "screenshot_available": bool(
                    (raw.get("screenshot") or {}).get("screenshot_available")
                )
            },
            "recovery_available": True,
        },
    )

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "captcha_or_action_required",
            "pages": [
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
                    ],
                    "meta": {"found_text": "Найдено 2"},
                }
            ],
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
            "screenshot": {"screenshot_available": True, "screenshot_filename": "cap.png"},
        }

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=1),
        paths=paths,
        page_reader=reader,
        fetch_details=True,
        detail_limit=10,
    )
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["action"]["code"] == "open_challenge"
    assert len(report["details"]) == 1
    assert report["code"] != "browser_proxy_unavailable"


def test_public_view_infers_recovery_from_legacy_state_without_flag(tmp_path: Path) -> None:
    """Legacy challenge_active (no recovery_available) must still expose URL."""
    paths = _paths(tmp_path)
    paths.ensure()
    raw = {
        "status": "operator_action_required",
        "code": "browser_captcha_or_action_required",
        "detected_at": "2026-09-10T16:28:37Z",
        "challenge_url": "https://hh.ru/account/captcha?backurl=https%3A%2F%2Fhh.ru%2Fvacancy%2F1",
        "challenge_title": "Подтвердите, что вы не робот",
        "screenshot_available": True,
        "screenshot_filename": "captcha.png",
        "progress": {"checked_count": 250},
    }
    (paths.state_dir / "challenge_active.json").write_text(
        __import__("json").dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (paths.state_dir / "challenges").mkdir(parents=True, exist_ok=True)
    (paths.state_dir / "challenges" / "captcha.png").write_bytes(b"\x89PNG")
    view = public_challenge_view(paths)
    assert view is not None
    assert view["recovery_available"] is True
    assert "account/captcha" in (view["challenge_url"] or "")
    assert view["screenshot_available"] is True


def test_acquire_orchestration_path_persists_state_for_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suitable-style acquire → real state writer → public API view reads same files."""
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setenv("HH_CAPTCHA_TG", "0")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def reader(**_kwargs: Any) -> dict[str, Any]:
        page = _ShotPage(url="https://hh.ru/account/captcha?state=abc", title="SmartCaptcha")
        evidence = capture_and_persist_live_challenge(
            page,
            vacancy_id="137221568",
            progress={"pages_fetched": 5, "pages_planned": 5, "checked_count": 250},
            paths=paths,
        )
        return {
            "kind": "captcha_or_action_required",
            "pages": [
                {
                    "page": 0,
                    "status": "ok",
                    "url": "https://hh.ru/search/vacancy",
                    "items": [
                        {
                            "external_id": "137221568",
                            "title": "A",
                            "url": "https://hh.ru/vacancy/137221568",
                            "employer_name": "X",
                        }
                    ],
                    "meta": {"found_text": "Найдено 1"},
                }
            ],
            "details": [],
            "wall_detail_id": "137221568",
            "challenge_url": evidence["challenge_url"],
            "challenge_title": evidence["challenge_title"],
            "screenshot": evidence["screenshot"],
            "challenge": evidence["challenge"],
        }

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=1),
        paths=paths,
        page_reader=reader,
        fetch_details=True,
        detail_limit=10,
    )
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["action"]["code"] == ACTION_OPEN_CHALLENGE
    state = read_challenge_state(paths)
    assert state is not None
    assert state["challenge_url"]
    assert state["screenshot_available"] is True
    assert (paths.state_dir / "challenges" / state["screenshot_filename"]).is_file()
    view = public_challenge_view(paths)
    assert view is not None
    assert view["challenge_url"] == state["challenge_url"]
    assert view["screenshot_available"] is True
    assert view["recovery_available"] is True


def test_capture_ordering_persist_before_simulated_close(tmp_path: Path) -> None:
    events: list[str] = []
    paths = _paths(tmp_path)

    class _OrderedPage(_ShotPage):
        def screenshot(self, *, path: str, full_page: bool = False) -> None:
            events.append("screenshot")
            super().screenshot(path=path, full_page=full_page)

    page = _OrderedPage(url="https://hh.ru/showcaptcha?d=ord")
    evidence = capture_and_persist_live_challenge(page, paths=paths)
    events.append("state_written")
    events.append("context_close")
    assert evidence["challenge_url"]
    assert events == ["screenshot", "state_written", "context_close"]
    assert read_challenge_state(paths) is not None


def test_confirm_refuses_while_challenge_browser_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/account/captcha?state=1",
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    state = read_challenge_state(paths) or {}
    state["handoff_pid"] = os.getpid()  # current test process is "alive"
    challenge_state_path = paths.state_dir / "challenge_active.json"
    challenge_state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setattr("job_search_hh.session._profile_chrome_running", lambda _p: True)
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._inspect_live_challenge_browser",
        lambda *_a, **_k: {
            "state": "active",
            "url": "https://hh.ru/account/captcha?state=1",
            "title": "SmartCaptcha",
        },
    )
    result = confirm_challenge_cleared(paths)
    assert result["ok"] is False
    assert result["cleared"] is False
    assert result["code"] == "challenge_browser_open"
    assert "Решите CAPTCHA" in (result.get("message") or "")
    assert result.get("challenge_browser_state") == "active"
    assert read_challenge_state(paths) is not None


def test_confirm_probe_urls_never_include_challenge_url() -> None:
    captcha = "https://hh.ru/account/captcha?backurl=https%3A%2F%2Fhh.ru%2Fvacancy%2F1&state=x"
    urls = _confirm_probe_urls(challenge_url=captcha)
    assert urls == ["https://hh.ru/applicant/resumes"]
    assert captcha not in urls
    assert not any("captcha" in u.casefold() for u in urls)


def test_confirm_never_navigates_to_captured_challenge_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    captcha = (
        "https://samara.hh.ru/account/captcha?backurl=https%3A%2F%2Fsamara.hh.ru%2Fvacancy%2F1"
    )
    write_challenge_state(
        challenge_url=captcha,
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setattr("job_search_hh.session._profile_chrome_running", lambda _p: False)
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )
    navigated: list[str] = []

    def _probe(resolved: Any, *, lock: Any) -> dict[str, Any]:
        del lock
        target = "https://hh.ru/applicant/resumes"
        navigated.append(target)
        return {
            "kind": "ok",
            "url": target,
            "title": "Мои резюме",
            "navigated_urls": [target],
            "items": [{"external_id": "abc", "title": "Dev"}],
        }

    monkeypatch.setattr("job_search_hh.challenge_handoff._probe_authenticated_session", _probe)
    monkeypatch.setattr(
        "job_search_hh.session.confirm_login",
        lambda *_a, **_k: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    monkeypatch.setattr(
        "job_search_hh.connection.connection_status",
        lambda: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    result = confirm_challenge_cleared(paths)
    assert result["ok"] is True
    assert result["cleared"] is True
    assert navigated == ["https://hh.ru/applicant/resumes"]
    assert captcha not in navigated
    assert result.get("validation_target") == "https://hh.ru/applicant/resumes"
    assert read_challenge_state(paths) is None


def test_confirm_keeps_state_when_session_still_challenged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    captcha = "https://hh.ru/account/captcha?state=still"
    write_challenge_state(
        challenge_url=captcha,
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setattr("job_search_hh.session._profile_chrome_running", lambda _p: False)
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._probe_authenticated_session",
        lambda *_a, **_k: {
            "kind": "captcha_or_action_required",
            "url": "https://hh.ru/account/captcha?new=1",
            "title": "SmartCaptcha",
            "navigated_urls": ["https://hh.ru/applicant/resumes"],
            "items": [],
        },
    )
    result = confirm_challenge_cleared(paths)
    assert result["ok"] is False
    assert result["cleared"] is False
    assert result["code"] == "browser_captcha_or_action_required"
    assert result["navigated_urls"] == ["https://hh.ru/applicant/resumes"]
    assert captcha not in (result.get("navigated_urls") or [])
    assert read_challenge_state(paths) is not None


def test_confirm_clears_when_browser_closed_and_challenge_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/account/captcha?state=1",
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setattr("job_search_hh.session._profile_chrome_running", lambda _p: False)
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._probe_authenticated_session",
        lambda *_a, **_k: {
            "kind": "ok",
            "url": "https://hh.ru/applicant/resumes",
            "title": "Resumes",
            "navigated_urls": ["https://hh.ru/applicant/resumes"],
            "items": [{"external_id": "r1", "title": "T"}],
        },
    )
    monkeypatch.setattr(
        "job_search_hh.session.confirm_login",
        lambda *_a, **_k: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    monkeypatch.setattr(
        "job_search_hh.connection.connection_status",
        lambda: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    result = confirm_challenge_cleared(paths)
    assert result["ok"] is True
    assert result["cleared"] is True
    assert result["code"] == "ready"
    assert "доступен" in (result.get("message") or "")
    assert read_challenge_state(paths) is None


def test_confirm_solved_in_open_browser_stops_then_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="https://hh.ru/account/captcha?state=1",
        paths=paths,
        screenshot={"screenshot_available": True, "screenshot_filename": "a.png"},
    )
    state = read_challenge_state(paths) or {}
    state["handoff_pid"] = 424242
    (paths.state_dir / "challenge_active.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    live = {"chrome": True}

    def _chrome(_p: Any) -> bool:
        return bool(live["chrome"])

    monkeypatch.setattr("job_search_hh.session._profile_chrome_running", _chrome)
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._challenge_handoff_process_alive",
        lambda *_a, **_k: live["chrome"],
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._inspect_live_challenge_browser",
        lambda *_a, **_k: {
            "state": "solved",
            "url": "https://hh.ru/vacancy/1",
            "title": "Vacancy",
        },
    )

    stopped: list[bool] = []

    def _stop(*_a: Any, **_k: Any) -> None:
        stopped.append(True)
        live["chrome"] = False

    monkeypatch.setattr("job_search_hh.challenge_handoff._stop_challenge_browser", _stop)
    monkeypatch.setattr(
        "job_search_hh.browser._clear_stale_chromium_singleton", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff._probe_authenticated_session",
        lambda *_a, **_k: {
            "kind": "ok",
            "url": "https://hh.ru/applicant/resumes",
            "title": "Resumes",
            "navigated_urls": ["https://hh.ru/applicant/resumes"],
            "items": [],
        },
    )
    monkeypatch.setattr(
        "job_search_hh.session.confirm_login",
        lambda *_a, **_k: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    monkeypatch.setattr(
        "job_search_hh.connection.connection_status",
        lambda: {"status": "connected", "login_ready": True, "code": "ready"},
    )
    result = confirm_challenge_cleared(paths)
    assert stopped == [True]
    assert result["cleared"] is True
    assert result.get("validation_target") == "https://hh.ru/applicant/resumes"


def test_open_challenge_rejects_missing_url(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    write_challenge_state(
        challenge_url="",
        paths=paths,
        screenshot={"screenshot_available": False},
        capture_status=CAPTURE_FAILED,
    )
    with pytest.raises(SessionError, match="challenge_url_missing"):
        open_challenge_browser(paths=paths)
