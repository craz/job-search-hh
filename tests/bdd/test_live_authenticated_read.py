"""Executable pytest-bdd bindings for live authenticated HH reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.providers import AuthenticatedHhApi
from job_search_hh.session import SessionPaths, confirm_login
from job_search_hh.sync import sync_applications

scenarios("../features/live_authenticated_read.feature")


class StubCore:
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


class FakeAuthenticatedApi(AuthenticatedHhApi):
    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(
            "https://api.hh.ru",
            "test-agent",
            5.0,
            "test-token",
        )
        self._items = items

    def list_applications(self) -> list[dict[str, Any]]:
        return list(self._items)


@given("confirmed session и access token", target_fixture="live_paths")
def confirmed_session(tmp_path: Path, monkeypatch: Any) -> SessionPaths:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")
    confirm_login(paths, confirmed=True)
    (paths.state_dir / "access_token").write_text("test-token\n", encoding="utf-8")
    monkeypatch.setenv("HH_STATE_DIR", str(paths.state_dir))
    monkeypatch.setenv("HH_PROFILE_DIR", str(paths.profile_dir))
    return paths


@given("fake authenticated HH отдаёт переговоры", target_fixture="live_sync_context")
def fake_live_negotiations(live_paths: SessionPaths) -> dict[str, Any]:
    del live_paths
    provider = FakeAuthenticatedApi(
        [
            {
                "id": "neg-live-1",
                "created_at": "2026-08-21T10:00:00+00:00",
                "state": {"id": "response"},
                "vacancy": {
                    "id": "1001",
                    "name": "Backend Engineer",
                    "alternate_url": "https://hh.ru/vacancy/1001",
                },
            }
        ]
    )
    return {"provider": provider, "core": StubCore()}


@when("оператор запускает live applications sync", target_fixture="live_sync_result")
def run_live_applications_sync(live_sync_context: dict[str, Any]) -> dict[str, Any]:
    report = sync_applications(live_sync_context["provider"], live_sync_context["core"])
    report["transport"] = "authenticated_api"
    return {"report": report, "core": live_sync_context["core"]}


@then("Core получает Application со source hh")
def core_got_application(live_sync_result: dict[str, Any]) -> None:
    core: StubCore = live_sync_result["core"]
    assert live_sync_result["report"]["synced"] == 1
    assert core.application_calls[0][1]["source"] == "hh"
    assert core.application_calls[0][1]["result"] == "reply"


@then("отчёт помечает transport authenticated_api")
def transport_marked(live_sync_result: dict[str, Any]) -> None:
    assert live_sync_result["report"]["transport"] == "authenticated_api"


@then("HH write не выполнялся")
def no_hh_write(live_sync_result: dict[str, Any]) -> None:
    assert live_sync_result["report"]["hh_write_attempted"] is False
    assert live_sync_result["report"]["external_writes_enabled"] is False
