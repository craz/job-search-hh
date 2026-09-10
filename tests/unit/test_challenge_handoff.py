"""Unit tests for CAPTCHA challenge evidence + operator handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.challenge_handoff import (
    ACTION_OPEN_CHALLENGE,
    begin_challenge_handoff,
    captcha_tg_configured,
    capture_challenge_screenshot,
    clear_challenge_state,
    confirm_challenge_cleared,
    notify_challenge_telegram,
    public_challenge_view,
    read_challenge_state,
    write_challenge_state,
)
from job_search_hh.session import SessionPaths
from job_search_hh.vacancy_browser import STATUS_ACTION_REQUIRED, acquire_vacancies
from job_search_hh.vacancy_query import ExecutionPolicy, SearchCriteria
from job_search_hh.session import confirm_login


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


class _ShotPage:
    def __init__(self) -> None:
        self.called = False

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        self.called = True
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")


def test_capture_screenshot_from_challenged_page(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    page = _ShotPage()
    shot = capture_challenge_screenshot(page, paths=paths)
    assert page.called is True
    assert shot["screenshot_available"] is True
    assert (paths.state_dir / "challenges" / shot["screenshot_filename"]).is_file()


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
    monkeypatch.setattr(
        "job_search_hh.challenge_handoff.interactive_display_ready", lambda: False
    )
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
    state = read_challenge_state(paths)
    assert state is not None
    assert state["status"] == "operator_action_required"
    assert state["challenge_url"].endswith("showcaptcha?d=abc")
    view = public_challenge_view(paths)
    assert view is not None
    assert "screenshot_path" not in view
    assert view["screenshot_available"] is True


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
    # No active challenge → confirm reports cleared without probing the network.
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
            },
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
            "challenge": {"screenshot_available": bool((raw.get("screenshot") or {}).get("screenshot_available"))},
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
