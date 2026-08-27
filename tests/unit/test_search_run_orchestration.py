"""Unit tests for HH SearchRun orchestration (R2.2.4)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from job_search_hh.core_client import CoreError
from job_search_hh.search_run_orchestration import (
    criteria_from_snapshot,
    execution_for_browser,
    run_vacancy_search,
)
from job_search_hh.vacancy_browser import (
    STATUS_ACTION_REQUIRED,
    STATUS_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
)


class FakeCore:
    """In-memory CoreGateway subset for orchestration."""

    def __init__(self) -> None:
        self.profile: dict[str, Any] = {
            "id": "11111111-1111-1111-1111-111111111111",
            "text": "python",
            "area_id": "1",
            "salary": None,
            "experience": None,
            "employment": None,
            "schedule": None,
            "search_field": None,
            "only_with_salary": None,
        }
        self.runs: dict[str, dict[str, Any]] = {}
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.vacancies: dict[str, dict[str, Any]] = {}
        self.ingest_calls: list[dict[str, Any]] = []
        self.fail_ingest_ids: set[str] = set()
        self.profile_reads = 0

    def get_search_profile(self, profile_id: str) -> dict[str, Any]:
        self.profile_reads += 1
        if profile_id != self.profile["id"]:
            raise CoreError("http_404:missing")
        return dict(self.profile)

    def start_search_run(
        self,
        *,
        search_profile_id: str | None = None,
        acquisition_kind: str = "profile_search",
        execution: dict[str, Any] | None = None,
        candidate_context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        if acquisition_kind == "resume_suitable":
            criteria: dict[str, Any] = {}
            profile_id = None
        else:
            criteria = {
                "text": self.profile["text"],
                "area_id": self.profile["area_id"],
                "salary": self.profile.get("salary"),
                "experience": self.profile.get("experience"),
                "employment": self.profile.get("employment"),
                "schedule": self.profile.get("schedule"),
                "search_field": self.profile.get("search_field"),
                "only_with_salary": self.profile.get("only_with_salary"),
            }
            profile_id = search_profile_id
        run = {
            "id": run_id,
            "search_profile_id": profile_id,
            "acquisition_kind": acquisition_kind,
            "status": "running",
            "criteria_snapshot": criteria,
            "execution_snapshot": dict(execution or {}),
            "candidate_context_snapshot": candidate_context_snapshot,
            "found_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "error_count": 0,
            "source_total": None,
            "error_code": None,
            "recovery_hint": None,
        }
        self.runs[run_id] = run
        self.items[run_id] = []
        return dict(run)

    def add_search_run_item(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.runs[run_id]
        if run["status"] != "running":
            raise CoreError("http_409:terminal")
        ext = payload["source_external_id"]
        if any(i["source_external_id"] == ext for i in self.items[run_id]):
            raise CoreError("http_409:duplicate")
        item = {"id": str(uuid.uuid4()), "search_run_id": run_id, **payload}
        self.items[run_id].append(item)
        return item

    def ingest_vacancy(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ingest_calls.append(payload)
        ext = payload["external_id"]
        if ext in self.fail_ingest_ids:
            raise CoreError("http_500:ingest_boom")
        existing = self.vacancies.get(ext)
        if existing is None:
            vacancy = {"id": str(uuid.uuid4()), **payload}
            self.vacancies[ext] = vacancy
            return {"outcome": "created", "vacancy": vacancy}
        if existing.get("description") == payload.get("description") and existing.get(
            "title"
        ) == payload.get("title"):
            return {"outcome": "unchanged", "vacancy": existing}
        existing.update(payload)
        return {"outcome": "updated", "vacancy": existing}

    def finalize_search_run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.runs[run_id]
        if run["status"] != "running":
            raise CoreError("http_409:already_terminal")
        items = self.items[run_id]
        run["status"] = payload["status"]
        run["error_code"] = payload.get("error_code")
        run["recovery_hint"] = payload.get("recovery_hint")
        if "source_total" in payload:
            run["source_total"] = payload.get("source_total")
        run["created_count"] = sum(1 for i in items if i.get("outcome") == "created")
        run["updated_count"] = sum(1 for i in items if i.get("outcome") == "updated")
        run["unchanged_count"] = sum(1 for i in items if i.get("outcome") == "unchanged")
        run["error_count"] = sum(1 for i in items if i.get("outcome") == "error")
        run["found_count"] = len(items)
        run["finished_at"] = "2026-08-27T12:00:00Z"
        return dict(run)

    def get_candidate_context(self) -> dict[str, Any]:
        return {
            "hh_resume_link": None,
            "resume_content": None,
            "profile_version": None,
        }

    def get_search_run(self, run_id: str) -> dict[str, Any]:
        return dict(self.runs[run_id])

    def list_search_run_items(self, run_id: str) -> dict[str, Any]:
        items = list(self.items[run_id])
        return {"items": items, "total": len(items)}


def _detail(external_id: str, *, ok: bool = True) -> dict[str, Any]:
    if not ok:
        return {"external_id": external_id, "status": "failed", "code": "vacancy_detail_failed"}
    return {
        "external_id": external_id,
        "status": "ok",
        "code": "ready",
        "content": {
            "external_id": external_id,
            "title": f"Title {external_id}",
            "url": f"https://hh.ru/vacancy/{external_id}",
            "employer_id": "42",
            "employer_name": "Acme",
            "description": f"Full description for {external_id} scoring-ready.",
        },
    }


def _ok_acquire(
    *,
    ids: list[str] | None = None,
    fail_detail: str | None = None,
    duplicate_on_page: bool = False,
    pages: list[dict[str, Any]] | None = None,
    status: str = STATUS_AVAILABLE,
    code: str = "ready",
) -> dict[str, Any]:
    ids = ids or ["1001", "1002"]
    summaries = [
        {
            "external_id": i,
            "title": f"Title {i}",
            "url": f"https://hh.ru/vacancy/{i}",
            "source_page": 0,
        }
        for i in ids
    ]
    if duplicate_on_page:
        summaries.append(dict(summaries[0]))
    details = [_detail(i, ok=(i != fail_detail)) for i in ids]
    return {
        "status": status,
        "code": code,
        "pages": pages
        or [
            {
                "page": 0,
                "status": "ok",
                "items": summaries,
                "meta": {"observed_page_size": len(ids)},
            }
        ],
        "summaries": summaries,
        "details": details,
        "pagination": {
            "pages_fetched": 1,
            "max_pages": 1,
            "exhausted": False,
            "max_pages_reached": True,
            "partial": False,
            "failed_pages": 0,
            "detail_failures": 1 if fail_detail else 0,
        },
        "action": {"code": "none"},
        "recovery": None,
        "hh_writes": False,
    }


def test_execution_for_browser_omits_page_size() -> None:
    snap = execution_for_browser({"order": "relevance", "max_pages": 2, "page_size": 50})
    assert snap["transport"] == "browser"
    assert snap["order"] == "relevance"
    assert snap["max_pages"] == 2
    assert "page_size" not in snap


def test_criteria_from_snapshot_uses_area_id() -> None:
    criteria = criteria_from_snapshot({"text": "python", "area_id": "1"})
    assert criteria.text == "python"
    assert criteria.area == "1"


def test_success_ingest_and_items() -> None:
    core = FakeCore()
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        max_pages=1,
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(),
    )
    assert report["status"] == "success"
    run = report["search_run"]
    assert run["status"] == "success"
    assert run["created_count"] == 2
    assert run["error_count"] == 0
    assert "page_size" not in run["execution_snapshot"]
    assert run["execution_snapshot"]["transport"] == "browser"
    assert len(core.ingest_calls) == 2
    assert all(i.get("vacancy_id") for i in report["items"] if i["outcome"] != "error")


def test_immutable_snapshot_not_live_profile() -> None:
    core = FakeCore()

    def acquire_fn(*_a: Any, **_k: Any) -> dict[str, Any]:
        # Mutate profile mid-run; orchestration must keep started snapshot.
        core.profile["text"] = "golang"
        return _ok_acquire(ids=["1001"])

    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=acquire_fn,
    )
    assert report["status"] == "success"
    assert report["search_run"]["criteria_snapshot"]["text"] == "python"
    assert core.profile["text"] == "golang"
    assert core.profile_reads == 1


def test_duplicate_source_id_within_run_processed_once() -> None:
    core = FakeCore()
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001"], duplicate_on_page=True),
    )
    assert report["status"] == "success"
    assert len(core.ingest_calls) == 1
    assert len(core.items[report["search_run"]["id"]]) == 1


def test_detail_failure_continues_partial() -> None:
    core = FakeCore()
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(
            ids=["1001", "1002"],
            fail_detail="1001",
            status=STATUS_PARTIAL,
            code="vacancy_detail_failed",
        ),
    )
    assert report["status"] == "partial"
    run = report["search_run"]
    assert run["error_count"] == 1
    assert run["created_count"] == 1
    outcomes = {i["source_external_id"]: i["outcome"] for i in report["items"]}
    assert outcomes["1001"] == "error"
    assert outcomes["1002"] == "created"
    assert (
        next(i for i in report["items"] if i["source_external_id"] == "1001")["vacancy_id"] is None
    )


def test_ingest_failure_continues_partial() -> None:
    core = FakeCore()
    core.fail_ingest_ids.add("1001")
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001", "1002"]),
    )
    assert report["status"] == "partial"
    assert report["search_run"]["error_count"] == 1
    assert report["search_run"]["created_count"] == 1


def test_page_failure_after_first_page_partial_no_fake_items() -> None:
    core = FakeCore()
    pages = [
        {
            "page": 0,
            "status": "ok",
            "items": [
                {
                    "external_id": "1001",
                    "title": "A",
                    "url": "https://hh.ru/vacancy/1001",
                    "source_page": 0,
                }
            ],
            "meta": {},
        },
        {"page": 1, "status": "failed", "code": "search_page_failed", "items": [], "meta": {}},
    ]

    def acquire_fn(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "status": STATUS_PARTIAL,
            "code": "partial_pagination",
            "pages": pages,
            "summaries": pages[0]["items"],
            "details": [_detail("1001")],
            "pagination": {
                "pages_fetched": 2,
                "failed_pages": 1,
                "max_pages_reached": False,
                "partial": True,
            },
            "action": {"code": "none"},
            "recovery": None,
        }

    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        max_pages=2,
        core=core,  # type: ignore[arg-type]
        acquire_fn=acquire_fn,
    )
    assert report["status"] == "partial"
    assert len(report["items"]) == 1
    assert all(i["source_external_id"] != "page-1-failed" for i in report["items"])


def test_first_page_failure_failed() -> None:
    core = FakeCore()

    def acquire_fn(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "status": STATUS_UNAVAILABLE,
            "code": "search_page_failed",
            "pages": [{"page": 0, "status": "failed", "items": [], "meta": {}}],
            "summaries": [],
            "details": [],
            "pagination": {"failed_pages": 1, "pages_fetched": 1},
            "action": {"code": "none"},
            "recovery": {"kind": "search_page_failed"},
        }

    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=acquire_fn,
    )
    assert report["status"] == "failed"
    assert report["search_run"]["status"] == "failed"
    assert report["search_run"]["found_count"] == 0


def test_zero_result_success() -> None:
    core = FakeCore()

    def acquire_fn(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "status": STATUS_AVAILABLE,
            "code": "empty",
            "pages": [{"page": 0, "status": "ok", "items": [], "meta": {"observed_page_size": 0}}],
            "summaries": [],
            "details": [],
            "pagination": {
                "pages_fetched": 1,
                "max_pages_reached": False,
                "exhausted": True,
                "failed_pages": 0,
            },
            "action": {"code": "none"},
            "recovery": None,
        }

    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=acquire_fn,
    )
    assert report["status"] == "success"
    assert report["search_run"]["found_count"] == 0
    assert report["search_run"]["created_count"] == 0


def test_max_pages_reached_is_success_not_partial() -> None:
    core = FakeCore()
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        max_pages=1,
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001"]),
    )
    assert report["status"] == "success"
    assert report["acquisition"]["pagination"]["max_pages_reached"] is True


def test_action_required_before_work_failed() -> None:
    core = FakeCore()

    def acquire_fn(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "status": STATUS_ACTION_REQUIRED,
            "code": "browser_captcha_or_action_required",
            "pages": [],
            "summaries": [],
            "details": [],
            "pagination": {},
            "action": {"code": "confirm_login"},
            "recovery": {"kind": "action_required"},
        }

    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=acquire_fn,
    )
    assert report["status"] == "failed"
    assert report["search_run"]["status"] == "failed"
    assert report["code"] == "browser_captcha_or_action_required"


def test_repeat_run_unchanged_and_new_run_id() -> None:
    core = FakeCore()
    first = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001"]),
    )
    second = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001"]),
    )
    assert first["search_run"]["id"] != second["search_run"]["id"]
    assert first["search_run"]["created_count"] == 1
    assert second["search_run"]["unchanged_count"] == 1
    assert len(core.vacancies) == 1


def test_terminal_immutability_blocks_new_items() -> None:
    core = FakeCore()
    report = run_vacancy_search(
        search_profile_id=core.profile["id"],
        core=core,  # type: ignore[arg-type]
        acquire_fn=lambda *a, **k: _ok_acquire(ids=["1001"]),
    )
    run_id = report["search_run"]["id"]
    with pytest.raises(CoreError):
        core.add_search_run_item(
            run_id,
            {
                "source_external_id": "9999",
                "outcome": "created",
                "vacancy_id": str(uuid.uuid4()),
            },
        )
