"""Executable pytest-bdd bindings for gated limited apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.apply import limited_apply, load_apply_plan
from job_search_hh.apply_transport import RecordingLiveApplyTransport

scenarios("../features/apply_limited.feature")

FIXTURE = Path(__file__).parents[1] / "fixtures" / "apply_plan.json"


@given("есть план limited apply на вакансию hh", target_fixture="limited_plan")
def synthetic_plan() -> list[dict[str, Any]]:
    return load_apply_plan(FIXTURE)


@given("внешние записи HH выключены", target_fixture="writes_enabled")
def writes_disabled() -> bool:
    return False


@given("внешние записи HH включены", target_fixture="writes_enabled")
def writes_enabled() -> bool:
    return True


@given("оператор передал явный флаг авторизации записи", target_fixture="authorized")
def authorization_flag() -> bool:
    return True


@when(
    "оператор запускает apply limited без авторизации записи",
    target_fixture="limited_result",
)
def run_limited_unauthorized(
    limited_plan: list[dict[str, Any]], writes_enabled: bool
) -> dict[str, Any]:
    return limited_apply(
        limited_plan,
        external_writes_enabled=writes_enabled,
        authorized=False,
        limit=1,
        transport=RecordingLiveApplyTransport(),
    )


@when(
    "оператор запускает apply limited через recording transport",
    target_fixture="limited_result",
)
def run_limited_with_recording(
    limited_plan: list[dict[str, Any]], writes_enabled: bool, authorized: bool
) -> dict[str, Any]:
    return limited_apply(
        limited_plan,
        external_writes_enabled=writes_enabled,
        authorized=authorized,
        limit=1,
        transport=RecordingLiveApplyTransport(),
    )


@then("команда отказывает с external_writes_disabled")
def refused_disabled(limited_result: dict[str, Any]) -> None:
    assert limited_result["execution"] == "refused"
    assert limited_result["errors"][0]["error"] == "external_writes_disabled"


@then("limited apply не пытался писать в HH")
def no_hh_write(limited_result: dict[str, Any]) -> None:
    assert limited_result["hh_write_attempted"] is False


@then("ответ mode limited и execution completed")
def completed_limited(limited_result: dict[str, Any]) -> None:
    assert limited_result["mode"] == "limited"
    assert limited_result["execution"] == "completed"
    assert limited_result["items"][0]["status"] == "submitted"


@then("limited apply отметил hh_write_attempted")
def write_attempted(limited_result: dict[str, Any]) -> None:
    assert limited_result["hh_write_attempted"] is True


@then("captcha_stop политика включена")
def captcha_policy(limited_result: dict[str, Any]) -> None:
    assert limited_result["captcha_stop"] is True
