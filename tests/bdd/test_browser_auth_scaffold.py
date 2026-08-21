"""Executable pytest-bdd bindings for browser/auth scaffold diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.session import SessionPaths, session_status

scenarios("../features/browser_auth_scaffold.feature")


@given("подготовлены каталоги profile и state", target_fixture="session_paths")
def prepared_paths(tmp_path: Path) -> SessionPaths:
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    paths.ensure()
    return paths


@when("оператор запрашивает session status", target_fixture="session_report")
def request_session_status(session_paths: SessionPaths) -> dict[str, Any]:
    return session_status(session_paths)


@then("chromium не установлен")
def chromium_missing(session_report: dict[str, Any]) -> None:
    assert session_report["chromium_installed"] is False
    assert session_report["browser_automation"] == "scaffold"
    assert session_report["novnc_configured"] is False


@then("profile lock доступен")
def profile_lock_ready(session_report: dict[str, Any]) -> None:
    assert session_report["profile_lock"] == "unlocked"


@then("auth session отсутствует")
def auth_absent(session_report: dict[str, Any]) -> None:
    assert session_report["auth_session"] == "absent"


@then("session status держит внешние записи выключенными")
def writes_disabled(session_report: dict[str, Any]) -> None:
    assert session_report["external_writes_enabled"] is False
