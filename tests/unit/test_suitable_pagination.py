"""Unit coverage for resume-suitable page traversal and continuation knobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from job_search_hh.resume_suitable import map_resume_suitable_query
from job_search_hh.search_run_orchestration import execution_for_browser, run_resume_suitable_search
from job_search_hh.session import SessionPaths, confirm_login


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def test_map_resume_suitable_query_emits_page() -> None:
    mapped = map_resume_suitable_query("resume-1", page=4, order="publication_time")
    assert mapped.query["page"] == "4"
    assert mapped.query["resume"] == "resume-1"
    assert mapped.query["order_by"] == "publication_time"


def test_execution_for_browser_includes_start_page() -> None:
    payload = execution_for_browser({"order": "publication_time"}, max_pages=5, start_page=7)
    assert payload["max_pages"] == 5
    assert payload["start_page"] == 7
    assert payload["transport"] == "browser"


def _detail(external_id: str, title: str, url: str) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "status": "ok",
        "code": "ready",
        "content": {
            "external_id": external_id,
            "title": title,
            "url": url,
            "employer_name": "Acme",
            "description": "desc",
            "archived": False,
        },
    }


def test_run_resume_suitable_continuation_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    seen_pages: list[int] = []
    known: set[str] = set()
    item_outcomes: list[str] = []

    def page_reader(*, page_urls: list[tuple[int, str]], **_kwargs: Any) -> dict[str, Any]:
        seen_pages.extend(index for index, _ in page_urls)
        pages = []
        details = []
        for index, url in page_urls:
            items = [
                {
                    "external_id": f"ext-{index}-a",
                    "title": "A",
                    "url": f"https://hh.ru/vacancy/{index}a",
                },
                {
                    "external_id": f"ext-{index}-b",
                    "title": "B",
                    "url": f"https://hh.ru/vacancy/{index}b",
                },
            ]
            pages.append(
                {
                    "page": index,
                    "url": url,
                    "status": "ok",
                    "code": "ready",
                    "items": items,
                    "meta": {
                        "found_text": "Найдено 2845 подходящих вакансий для резюме",
                        "observed_page_size": 2,
                    },
                }
            )
            for item in items:
                details.append(_detail(item["external_id"], item["title"], item["url"]))
        return {"kind": "ok", "pages": pages, "details": details}

    def ingest(payload: dict[str, Any]) -> dict[str, Any]:
        external = str(payload.get("external_id") or "")
        if external in known:
            return {"outcome": "unchanged", "vacancy": {"id": f"v-{external}"}}
        known.add(external)
        return {"outcome": "created", "vacancy": {"id": f"v-{external}"}}

    def add_item(_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        outcome = str(payload.get("outcome") or "")
        item_outcomes.append(outcome)
        return dict(payload)

    def finalize(_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        created = sum(1 for item in item_outcomes if item == "created")
        unchanged = sum(1 for item in item_outcomes if item == "unchanged")
        return {
            "id": "run-1",
            "status": payload.get("status") or "success",
            "found_count": created + unchanged,
            "created_count": created,
            "updated_count": 0,
            "unchanged_count": unchanged,
            "finished_at": "2026-09-10T00:00:00Z",
            "source_total": payload.get("source_total"),
            "error_code": payload.get("error_code"),
        }

    core = MagicMock()
    core.start_search_run.return_value = {"id": "run-1", "status": "running"}
    core.ingest_vacancy.side_effect = ingest
    core.add_search_run_item.side_effect = add_item
    core.finalize_search_run.side_effect = finalize

    monkeypatch.setattr(
        "job_search_hh.search_run_orchestration._candidate_context_for_active_resume",
        lambda *_args, **_kwargs: {
            "hh_resume_external_id": "resume-xyz",
            "hh_resume_title": "Test Resume",
        },
    )

    first = run_resume_suitable_search(
        max_pages=2,
        start_page=5,
        core=core,
        paths=paths,
        page_reader=page_reader,
        timeout_seconds=5.0,
    )
    assert seen_pages == [5, 6]
    assert first["ok"] is True
    assert first["source_total"] == 2845
    assert first["acquisition"]["pagination"]["start_page"] == 5
    assert first["acquisition"]["pagination"]["next_page"] == 7
    assert first["acquisition"]["pagination"]["more_remaining"] is True
    assert first["search_run"]["created_count"] == 4
    assert first["search_run"]["unchanged_count"] == 0

    seen_pages.clear()
    item_outcomes.clear()

    def overlapping_reader(*, page_urls: list[tuple[int, str]], **_kwargs: Any) -> dict[str, Any]:
        seen_pages.extend(index for index, _ in page_urls)
        pages = []
        details = []
        for index, url in page_urls:
            items = [
                {
                    "external_id": "ext-6-b",
                    "title": "B",
                    "url": "https://hh.ru/vacancy/6b",
                },
                {
                    "external_id": f"ext-{index}-new",
                    "title": "New",
                    "url": f"https://hh.ru/vacancy/{index}new",
                },
            ]
            pages.append(
                {
                    "page": index,
                    "url": url,
                    "status": "ok",
                    "code": "ready",
                    "items": items,
                    "meta": {
                        "found_text": "Найдено 2845 подходящих вакансий для резюме",
                        "observed_page_size": 2,
                    },
                }
            )
            for item in items:
                details.append(_detail(item["external_id"], item["title"], item["url"]))
        return {"kind": "ok", "pages": pages, "details": details}

    second = run_resume_suitable_search(
        max_pages=1,
        start_page=7,
        core=core,
        paths=paths,
        page_reader=overlapping_reader,
        timeout_seconds=5.0,
    )
    assert seen_pages == [7]
    assert second["acquisition"]["pagination"]["start_page"] == 7
    assert second["search_run"]["unchanged_count"] >= 1
    assert second["search_run"]["created_count"] >= 1
