"""Executable pytest-bdd bindings for read-only HH vacancy sync."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.capabilities import current_capabilities
from job_search_hh.providers import FixtureProvider
from job_search_hh.sync import sync_vacancies

scenarios("../features/vacancy_sync.feature")


class StubCore:
    """In-memory Core gateway recording idempotent vacancy creates."""

    def __init__(self) -> None:
        self.by_key: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self.calls.append((idempotency_key, payload))
        if idempotency_key in self.by_key:
            return self.by_key[idempotency_key]
        created = {
            "id": f"core-{payload['external_id']}",
            "source": payload["source"],
            "external_id": payload["external_id"],
            "title": payload["title"],
        }
        self.by_key[idempotency_key] = created
        return created


@given("fake HH API отдаёт публичные вакансии", target_fixture="sync_context")
def fake_hh_api() -> dict[str, Any]:
    provider = FixtureProvider(
        [
            {
                "id": "1001",
                "name": "Backend Engineer",
                "alternate_url": "https://hh.ru/vacancy/1001",
                "employer": {"id": "55", "name": "Example Labs"},
                "snippet": {
                    "requirement": "Python",
                    "responsibility": "Build APIs",
                },
            },
            {
                "id": "1002",
                "name": "Platform Engineer",
                "alternate_url": "https://hh.ru/vacancy/1002",
                "employer": {"id": "55", "name": "Example Labs"},
            },
        ]
    )
    return {"provider": provider, "core": StubCore()}


@when("оператор запускает read-only sync вакансий", target_fixture="sync_result")
def run_sync(sync_context: dict[str, Any]) -> dict[str, Any]:
    first = sync_vacancies(
        sync_context["provider"], sync_context["core"], text="python", per_page=10
    )
    second = sync_vacancies(
        sync_context["provider"], sync_context["core"], text="python", per_page=10
    )
    return {"first": first, "second": second, "core": sync_context["core"]}


@then("Core получает нормализованные вакансии со source hh")
def core_receives_hh_vacancies(sync_result: dict[str, Any]) -> None:
    core: StubCore = sync_result["core"]
    assert sync_result["first"]["synced"] == 2
    assert {payload["source"] for _, payload in core.calls} == {"hh"}
    assert {payload["external_id"] for _, payload in core.calls[:2]} == {"1001", "1002"}


@then("внешние записи на HH остаются выключенными")
def writes_stay_disabled(sync_result: dict[str, Any]) -> None:
    assert sync_result["first"]["external_writes_enabled"] is False
    assert current_capabilities().external_writes_enabled is False


@then("повторный sync не создаёт дубликаты")
def replay_is_idempotent(sync_result: dict[str, Any]) -> None:
    core: StubCore = sync_result["core"]
    assert sync_result["second"]["synced"] == 2
    assert len(core.by_key) == 2
    assert len(core.calls) == 4
    assert {item["core_id"] for item in sync_result["second"]["items"]} == {
        "core-1001",
        "core-1002",
    }
