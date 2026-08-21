"""Executable pytest-bdd bindings for operator noVNC login markers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.session import SessionPaths, auth_status, confirm_login, open_login

scenarios("../features/operator_novnc_login.feature")


class FakeLauncher:
    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        assert profile_dir.exists()
        assert login_url.startswith("https://")


@given("подготовлены каталоги profile и state для login", target_fixture="login_paths")
def prepared_login_paths(tmp_path: Path) -> SessionPaths:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    paths.ensure()
    return paths


@given("Chromium отмечен как установленный")
def chromium_flag(monkeypatch: Any) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")


@when("оператор открывает login без реального браузера", target_fixture="open_report")
def open_without_real_browser(login_paths: SessionPaths) -> dict[str, Any]:
    return open_login(login_paths, launcher=FakeLauncher())


@then("auth session pending_operator")
def pending_operator(open_report: dict[str, Any], login_paths: SessionPaths) -> None:
    assert open_report["auth_session"] == "pending_operator"
    assert auth_status(login_paths)["auth_session"] == "pending_operator"


@then("captcha bypass выключен")
def no_captcha_bypass(open_report: dict[str, Any]) -> None:
    assert open_report["captcha_bypass"] is False


@when("оператор подтверждает login", target_fixture="confirm_report")
def confirm_operator_login(login_paths: SessionPaths) -> dict[str, Any]:
    return confirm_login(login_paths, confirmed=True)


@then("auth session present")
def session_present(confirm_report: dict[str, Any]) -> None:
    assert confirm_report["auth_session"] == "present"


@then("login_ready включён")
def login_ready_true(confirm_report: dict[str, Any]) -> None:
    assert confirm_report["login_ready"] is True
