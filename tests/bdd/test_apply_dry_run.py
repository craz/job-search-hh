"""Executable pytest-bdd bindings for HH apply dry-run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.apply import dry_run_apply, load_apply_plan
from job_search_hh.apply_transport import FakeApplyTransport
from job_search_hh.capabilities import current_capabilities

scenarios("../features/apply_dry_run.feature")

FIXTURE = Path(__file__).parents[1] / "fixtures" / "apply_plan.json"


@given("есть синтетический план отклика на вакансию hh", target_fixture="dry_run_context")
def synthetic_plan() -> dict[str, Any]:
    transport = FakeApplyTransport()
    return {"plan": load_apply_plan(FIXTURE), "transport": transport}


@when("оператор запускает apply dry-run", target_fixture="dry_run_result")
def run_dry_run(dry_run_context: dict[str, Any]) -> dict[str, Any]:
    report = dry_run_apply(dry_run_context["plan"], dry_run_context["transport"])
    return {"report": report, "transport": dry_run_context["transport"]}


@then("ответ содержит would_send для вакансии")
def response_has_would_send(dry_run_result: dict[str, Any]) -> None:
    report = dry_run_result["report"]
    assert report["mode"] == "dry-run"
    assert report["simulated"] == 1
    assert report["items"][0]["vacancy_external_id"] == "1001"
    assert report["items"][0]["would_send"]["path"] == "/negotiations"
    assert "message" in report["items"][0]["would_send"]["body_keys"]


@then("HH write не выполнялся")
def hh_write_not_attempted(dry_run_result: dict[str, Any]) -> None:
    assert dry_run_result["report"]["hh_write_attempted"] is False
    assert dry_run_result["transport"].write_attempted is False


@then("external_writes_enabled остаётся false")
def writes_disabled(dry_run_result: dict[str, Any]) -> None:
    assert dry_run_result["report"]["external_writes_enabled"] is False
    assert current_capabilities().external_writes_enabled is False


@then("Core Application не создаётся")
def core_not_written(dry_run_result: dict[str, Any]) -> None:
    assert dry_run_result["report"]["core_application_created"] is False
