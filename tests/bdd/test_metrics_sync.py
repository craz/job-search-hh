"""Executable pytest-bdd bindings for read-only HH metrics sync."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.capabilities import current_capabilities
from job_search_hh.providers import FixtureProvider
from job_search_hh.sync import sync_metrics

scenarios("../features/metrics_sync.feature")


class StubCore:
    """In-memory Core gateway recording idempotent metric upserts."""

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


@given("fake HH API отдаёт дневные снимки метрик", target_fixture="metric_sync_context")
def fake_metrics() -> dict[str, Any]:
    provider = FixtureProvider(
        [
            {
                "metric_date": "2026-08-20",
                "views_total": 12,
                "views_new": 3,
                "applications": 2,
                "replies": 1,
                "notes": "hh fixture day",
            }
        ]
    )
    return {"provider": provider, "core": StubCore()}


@when("оператор запускает read-only sync метрик", target_fixture="metric_sync_result")
def run_metric_sync(metric_sync_context: dict[str, Any]) -> dict[str, Any]:
    first = sync_metrics(metric_sync_context["provider"], metric_sync_context["core"])
    second = sync_metrics(metric_sync_context["provider"], metric_sync_context["core"])
    return {"first": first, "second": second, "core": metric_sync_context["core"]}


@then("Core получает нормализованные Daily Metric")
def core_receives_metrics(metric_sync_result: dict[str, Any]) -> None:
    core: StubCore = metric_sync_result["core"]
    assert metric_sync_result["first"]["synced"] == 1
    assert core.calls[0][1] == "2026-08-20"
    assert core.calls[0][2]["applications"] == 2
    assert core.calls[0][2]["views_total"] == 12


@then("sync метрик не включает внешние записи на HH")
def writes_stay_disabled(metric_sync_result: dict[str, Any]) -> None:
    assert metric_sync_result["first"]["external_writes_enabled"] is False
    assert current_capabilities().external_writes_enabled is False


@then("повторный sync метрик не создаёт конфликт")
def replay_is_idempotent(metric_sync_result: dict[str, Any]) -> None:
    core: StubCore = metric_sync_result["core"]
    assert metric_sync_result["second"]["synced"] == 1
    assert metric_sync_result["second"]["errors"] == []
    assert len(core.by_key) == 1
    assert len(core.calls) == 2
