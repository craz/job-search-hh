"""Executable pytest-bdd bindings for resume-view enriched metrics sync."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.providers import AuthenticatedHhApi
from job_search_hh.sync import sync_metrics

scenarios("../features/resume_views_metrics.feature")


class StubCore:
    def __init__(self) -> None:
        self.by_key: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        raise AssertionError("vacancy writes are out of scope for metrics sync")

    def list_vacancies(self) -> list[dict[str, Any]]:
        return []

    def create_application(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        raise AssertionError("application writes are out of scope for metrics sync")

    def upsert_metric(
        self, metric_date: str, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        self.calls.append((idempotency_key, metric_date, payload))
        if idempotency_key in self.by_key:
            return self.by_key[idempotency_key]
        stored = {"metric_date": metric_date, **payload}
        self.by_key[idempotency_key] = stored
        return stored


class FakeRichMetricsApi(AuthenticatedHhApi):
    def __init__(self) -> None:
        super().__init__("https://api.hh.ru", "ua", 5.0, "token")

    def list_applications(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "n1",
                "state": "response",
                "vacancy": {"id": "1001"},
            }
        ]

    def resume_view_totals(self) -> tuple[int | None, int | None, str]:
        return 17, 2, "resumes_mine"


@given("fake authenticated HH отдаёт negotiations и resumes", target_fixture="rich_ctx")
def fake_rich_metrics() -> dict[str, Any]:
    return {"provider": FakeRichMetricsApi(), "core": StubCore()}


@when("оператор запускает live metrics sync", target_fixture="rich_result")
def run_rich_metrics(rich_ctx: dict[str, Any]) -> dict[str, Any]:
    report = sync_metrics(rich_ctx["provider"], rich_ctx["core"])
    report["transport"] = "authenticated_api"
    return {"report": report, "core": rich_ctx["core"]}


@then("Core получает Daily Metric с views_total")
def core_has_views(rich_result: dict[str, Any]) -> None:
    core: StubCore = rich_result["core"]
    assert rich_result["report"]["synced"] == 1
    assert core.calls[0][2]["views_total"] == 17
    assert core.calls[0][2]["views_new"] == 2
    assert core.calls[0][2]["applications"] == 1


@then("notes указывают resumes_mine")
def notes_mention_resumes(rich_result: dict[str, Any]) -> None:
    assert "resumes_mine" in rich_result["core"].calls[0][2]["notes"]


@then("HH write не выполнялся")
def no_hh_write(rich_result: dict[str, Any]) -> None:
    assert rich_result["report"]["hh_write_attempted"] is False
