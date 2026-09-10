"""Unit tests for manual HH vacancy content refresh."""

from __future__ import annotations

import uuid
from typing import Any

from job_search_hh.core_client import CoreError
from job_search_hh.vacancy_content_refresh import refresh_vacancy_content


class FakeCore:
    def __init__(self) -> None:
        self.vacancies: dict[str, dict[str, Any]] = {}
        self.ingest_calls: list[dict[str, Any]] = []

    def ingest_vacancy(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ingest_calls.append(payload)
        ext = payload["external_id"]
        existing = self.vacancies.get(ext)
        if existing is None:
            vacancy = {"id": str(uuid.uuid4()), "source_status": "active", **payload}
            self.vacancies[ext] = vacancy
            return {"outcome": "created", "vacancy": vacancy}
        if existing.get("description") == payload.get("description") and existing.get(
            "title"
        ) == payload.get("title"):
            return {"outcome": "unchanged", "vacancy": existing}
        existing.update(payload)
        existing["source_status"] = "archived" if payload.get("archived") else "active"
        return {"outcome": "updated", "vacancy": existing}


class FakePaths:
    profile_dir = "/tmp/fake-hh-profile"


def test_refresh_updated_and_unchanged(monkeypatch) -> None:
    core = FakeCore()
    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.auth_status",
        lambda _paths: {"login_ready": True},
    )

    class Lock:
        def status(self) -> str:
            return "unlocked"

        def acquire(self, _name: str) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.ProfileLock",
        lambda _dir: Lock(),
    )

    content = {
        "external_id": "555",
        "title": "Python",
        "url": "https://hh.ru/vacancy/555",
        "employer_id": "9",
        "employer_name": "Acme",
        "description": "Full description for scoring-ready vacancy body.",
        "archived": False,
    }

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "ok", "content": content}

    first = refresh_vacancy_content(
        "555",
        paths=FakePaths(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        page_reader=reader,
    )
    assert first["ok"] is True
    assert first["outcome"] == "created"
    assert first["ux_status"] == "updated"

    second = refresh_vacancy_content(
        "555",
        paths=FakePaths(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        page_reader=reader,
    )
    assert second["ok"] is True
    assert second["outcome"] == "unchanged"
    assert second["ux_status"] == "unchanged"

    content = {**content, "description": "Changed full description for scoring-ready vacancy."}

    def reader2(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "ok", "content": content}

    third = refresh_vacancy_content(
        "555",
        paths=FakePaths(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        page_reader=reader2,
    )
    assert third["ok"] is True
    assert third["outcome"] == "updated"
    assert third["ux_status"] == "updated"


def test_refresh_unavailable_when_archived(monkeypatch) -> None:
    core = FakeCore()
    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.auth_status",
        lambda _paths: {"login_ready": True},
    )

    class Lock:
        def status(self) -> str:
            return "unlocked"

        def acquire(self, _name: str) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.ProfileLock",
        lambda _dir: Lock(),
    )

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "content": {
                "external_id": "556",
                "title": "Gone",
                "url": "https://hh.ru/vacancy/556",
                "employer_id": "9",
                "employer_name": "Acme",
                "description": "Full description for scoring-ready vacancy body.",
                "archived": True,
            },
        }

    report = refresh_vacancy_content(
        "556",
        paths=FakePaths(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        page_reader=reader,
    )
    assert report["ok"] is True
    assert report["ux_status"] == "unavailable"


def test_refresh_core_error(monkeypatch) -> None:
    class BoomCore(FakeCore):
        def ingest_vacancy(self, payload: dict[str, Any]) -> dict[str, Any]:
            raise CoreError("http_500:boom")

    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.auth_status",
        lambda _paths: {"login_ready": True},
    )

    class Lock:
        def status(self) -> str:
            return "unlocked"

        def acquire(self, _name: str) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.vacancy_content_refresh.ProfileLock",
        lambda _dir: Lock(),
    )

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "content": {
                "external_id": "557",
                "title": "X",
                "url": "https://hh.ru/vacancy/557",
                "employer_id": "9",
                "employer_name": "Acme",
                "description": "Full description for scoring-ready vacancy body.",
            },
        }

    report = refresh_vacancy_content(
        "557",
        paths=FakePaths(),  # type: ignore[arg-type]
        core=BoomCore(),  # type: ignore[arg-type]
        page_reader=reader,
    )
    assert report["ok"] is False
    assert report["ux_status"] == "error"
    assert report["code"] == "core_ingest_failed"
