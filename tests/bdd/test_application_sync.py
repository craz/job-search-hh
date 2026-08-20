"""Executable pytest-bdd bindings for read-only HH application sync."""

from __future__ import annotations

from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.capabilities import current_capabilities
from job_search_hh.providers import FixtureProvider
from job_search_hh.sync import sync_applications

scenarios("../features/application_sync.feature")


class StubCore:
    """In-memory Core gateway for vacancy resolve and application creates."""

    def __init__(self) -> None:
        self.vacancies: list[dict[str, Any]] = [
            {
                "id": "core-vac-1001",
                "source": "hh",
                "external_id": "1001",
                "title": "Backend Engineer",
            }
        ]
        self.applications_by_key: dict[str, dict[str, Any]] = {}
        self.application_calls: list[tuple[str, dict[str, Any]]] = []

    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        del idempotency_key
        created = {
            "id": f"core-vac-{payload['external_id']}",
            "source": payload["source"],
            "external_id": payload["external_id"],
            "title": payload["title"],
        }
        self.vacancies.append(created)
        return created

    def list_vacancies(self) -> list[dict[str, Any]]:
        return list(self.vacancies)

    def create_application(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self.application_calls.append((idempotency_key, payload))
        if idempotency_key in self.applications_by_key:
            return self.applications_by_key[idempotency_key]
        created = {
            "id": f"core-app-{payload['external_id']}",
            "source": payload["source"],
            "external_id": payload["external_id"],
            "vacancy_id": payload["vacancy_id"],
        }
        self.applications_by_key[idempotency_key] = created
        return created


@given("fake HH API отдаёт существующие переговоры", target_fixture="app_sync_context")
def fake_negotiations() -> dict[str, Any]:
    provider = FixtureProvider(
        [
            {
                "id": "neg-1",
                "created_at": "2026-08-20T12:00:00+00:00",
                "state": "response",
                "vacancy": {"id": "1001"},
            }
        ]
    )
    return {"provider": provider, "core": StubCore()}


@given("Core уже знает связанные вакансии hh")
def core_has_vacancies(app_sync_context: dict[str, Any]) -> None:
    assert any(item["external_id"] == "1001" for item in app_sync_context["core"].vacancies)


@when("оператор запускает read-only sync откликов", target_fixture="app_sync_result")
def run_application_sync(app_sync_context: dict[str, Any]) -> dict[str, Any]:
    first = sync_applications(app_sync_context["provider"], app_sync_context["core"])
    second = sync_applications(app_sync_context["provider"], app_sync_context["core"])
    return {"first": first, "second": second, "core": app_sync_context["core"]}


@then("Core получает нормализованные Application со source hh")
def core_receives_applications(app_sync_result: dict[str, Any]) -> None:
    core: StubCore = app_sync_result["core"]
    assert app_sync_result["first"]["synced"] == 1
    assert core.application_calls[0][1]["source"] == "hh"
    assert core.application_calls[0][1]["result"] == "reply"
    assert core.application_calls[0][1]["vacancy_id"] == "core-vac-1001"


@then("sync откликов не включает внешние записи на HH")
def writes_stay_disabled(app_sync_result: dict[str, Any]) -> None:
    assert app_sync_result["first"]["external_writes_enabled"] is False
    assert current_capabilities().external_writes_enabled is False


@then("повторный sync откликов не создаёт дубликаты")
def replay_is_idempotent(app_sync_result: dict[str, Any]) -> None:
    core: StubCore = app_sync_result["core"]
    assert app_sync_result["second"]["synced"] == 1
    assert len(core.applications_by_key) == 1
    assert len(core.application_calls) == 2
    assert app_sync_result["second"]["items"][0]["core_id"] == "core-app-neg-1"
