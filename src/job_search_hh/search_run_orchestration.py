"""HH-owned SearchRun orchestration (R2.2.4).

Flow: SearchProfile → start SearchRun (immutable snapshots) → browser acquire →
detail → Core ingest → SearchRunItem → finalize.

Browser extractors never write Core; Core owns Vacancy hash/upsert and run
counters. Does not start Web/R2.2.5 or Scoring.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from job_search_hh.active_resume import read_stored_external_id
from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient, CoreError
from job_search_hh.normalize import NormalizeError, vacancy_detail_to_ingest
from job_search_hh.recovery import with_recovery
from job_search_hh.resume_suitable import map_resume_suitable_query, validate_resume_suitable_page
from job_search_hh.resumes import list_resumes
from job_search_hh.session import SessionPaths
from job_search_hh.vacancy_browser import (
    STATUS_ACTION_REQUIRED,
    STATUS_NOT_AUTHORIZED,
    STATUS_PARTIAL,
    STATUS_PERMISSION_BLOCKED,
    STATUS_UNAVAILABLE,
    VacancyPagesReader,
    acquire_vacancies,
)
from job_search_hh.vacancy_query import ExecutionPolicy, SearchCriteria

AcquireFn = Callable[..., dict[str, Any]]

_BLOCKING_ACQUIRE = frozenset(
    {
        STATUS_NOT_AUTHORIZED,
        STATUS_ACTION_REQUIRED,
        STATUS_PERMISSION_BLOCKED,
        STATUS_UNAVAILABLE,
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def criteria_from_snapshot(snapshot: dict[str, Any]) -> SearchCriteria:
    """Map SearchRun.criteria_snapshot to browser SearchCriteria (immutable)."""
    salary_raw = snapshot.get("salary")
    salary: int | None = None
    if isinstance(salary_raw, dict) and salary_raw.get("from") is not None:
        try:
            salary = int(salary_raw["from"])
        except (TypeError, ValueError):
            salary = None
    elif isinstance(salary_raw, (int, str)) and str(salary_raw).strip():
        try:
            salary = int(salary_raw)
        except (TypeError, ValueError):
            salary = None
    return SearchCriteria(
        text=str(snapshot["text"]) if snapshot.get("text") is not None else None,
        area=snapshot.get("area_id") or snapshot.get("area"),
        salary=salary,
        experience=str(snapshot["experience"]) if snapshot.get("experience") else None,
        employment=str(snapshot["employment"]) if snapshot.get("employment") else None,
        schedule=str(snapshot["schedule"]) if snapshot.get("schedule") else None,
        search_field=str(snapshot["search_field"]) if snapshot.get("search_field") else None,
        only_with_salary=snapshot.get("only_with_salary")
        if isinstance(snapshot.get("only_with_salary"), bool)
        else None,
    )


def execution_for_browser(
    snapshot: dict[str, Any] | None, *, max_pages: int | None = None
) -> dict[str, Any]:
    """Build Core execution payload for browser transport (no fake page_size)."""
    snap = dict(snapshot or {})
    order = str(snap.get("order") or "publication_time").strip() or "publication_time"
    pages = max_pages if max_pages is not None else snap.get("max_pages", 1)
    try:
        pages_int = max(1, min(int(pages), 20))
    except (TypeError, ValueError):
        pages_int = 1
    return {
        "order": order,
        "max_pages": pages_int,
        "transport": "browser",
    }


def _detail_map(details: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("external_id") or "").strip()
        if external_id and external_id not in out:
            out[external_id] = item
    return out


def _finalize(
    core: CoreClient,
    run_id: str,
    *,
    status: str,
    error_code: str | None = None,
    recovery_hint: str | None = None,
    source_total: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status}
    if error_code:
        payload["error_code"] = error_code
    if recovery_hint:
        payload["recovery_hint"] = recovery_hint
    if source_total is not None:
        payload["source_total"] = source_total
    return core.finalize_search_run(run_id, payload)


def _add_item(core: CoreClient, run_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return core.add_search_run_item(run_id, payload)
    except CoreError:
        return None


def run_vacancy_search(
    *,
    search_profile_id: str,
    max_pages: int = 1,
    order: str = "publication_time",
    core: CoreClient | None = None,
    paths: SessionPaths | None = None,
    acquire_fn: AcquireFn | None = None,
    page_reader: VacancyPagesReader | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Execute one bounded SearchRun end-to-end and return an observable report."""
    settings = Settings.from_env()
    client = core or CoreClient(settings.core_url, settings.timeout_seconds)
    checked_at = _utc_now()
    base: dict[str, Any] = {
        "operation": "vacancy_search_run",
        "checked_at": checked_at,
        "search_profile_id": search_profile_id,
        "search_run": None,
        "acquisition": None,
        "items": [],
        "hh_writes": False,
        "action": {"code": "none"},
    }

    try:
        profile = client.get_search_profile(search_profile_id)
    except CoreError as error:
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "search_profile_unavailable",
                "error": str(error),
            }
        )

    execution = execution_for_browser(
        {"order": order, "max_pages": max_pages},
        max_pages=max_pages,
    )
    try:
        run = client.start_search_run(
            search_profile_id=str(profile.get("id") or search_profile_id),
            acquisition_kind="profile_search",
            execution=execution,
        )
    except CoreError as error:
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "search_run_start_failed",
                "error": str(error),
            }
        )

    run_id = str(run.get("id") or "")
    base["search_run"] = {"id": run_id, "status": run.get("status")}
    raw_criteria = run.get("criteria_snapshot")
    criteria_snap: dict[str, Any] = raw_criteria if isinstance(raw_criteria, dict) else {}
    raw_execution = run.get("execution_snapshot")
    execution_snap: dict[str, Any] = (
        raw_execution if isinstance(raw_execution, dict) else dict(execution)
    )
    criteria = criteria_from_snapshot(criteria_snap)
    policy = ExecutionPolicy(
        order=str(execution_snap.get("order") or order),
        max_pages=int(execution_snap.get("max_pages") or max_pages),
        page_size=None,
    )

    acquirer = acquire_fn or acquire_vacancies
    try:
        acquisition = acquirer(
            criteria,
            policy,
            paths=paths or SessionPaths.from_env(),
            page_reader=page_reader,
            fetch_details=True,
            detail_limit=200,
            timeout_seconds=timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001 - finalize failed run
        try:
            finalized = _finalize(
                client,
                run_id,
                status="failed",
                error_code="transport_unavailable",
                recovery_hint=type(error).__name__,
            )
            base["search_run"] = finalized
        except CoreError:
            pass
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "transport_unavailable",
                "error": type(error).__name__,
            }
        )

    base["acquisition"] = {
        "status": acquisition.get("status"),
        "code": acquisition.get("code"),
        "pagination": acquisition.get("pagination"),
        "recovery": acquisition.get("recovery"),
    }

    acquire_status = str(acquisition.get("status") or "")
    acquire_code = str(acquisition.get("code") or "")
    pages = [p for p in list(acquisition.get("pages") or []) if isinstance(p, dict)]
    ok_pages = sum(1 for p in pages if str(p.get("status")) == "ok")
    failed_pages = sum(1 for p in pages if str(p.get("status")) != "ok")
    summaries = [s for s in list(acquisition.get("summaries") or []) if isinstance(s, dict)]
    details = _detail_map(
        [d for d in list(acquisition.get("details") or []) if isinstance(d, dict)]
    )

    # Blocking failure before any successful page → failed SearchRun.
    if acquire_status in _BLOCKING_ACQUIRE and ok_pages == 0:
        try:
            finalized = _finalize(
                client,
                run_id,
                status="failed",
                error_code=acquire_code or "search_page_failed",
                recovery_hint=str((acquisition.get("recovery") or {}).get("kind") or ""),
            )
            base["search_run"] = finalized
        except CoreError as error:
            base["error"] = str(error)
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": acquire_code or "search_page_failed",
                "action": acquisition.get("action") or {"code": "none"},
                "recovery": acquisition.get("recovery"),
            }
        )

    item_errors = 0
    item_ok = 0
    seen: set[str] = set()
    recorded_items: list[dict[str, Any]] = []

    for summary in summaries:
        external_id = str(summary.get("external_id") or "").strip()
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        page = summary.get("source_page")
        detail = details.get(external_id)
        if (
            detail is None
            or str(detail.get("status")) != "ok"
            or not isinstance(detail.get("content"), dict)
        ):
            item_errors += 1
            code = str((detail or {}).get("code") or "vacancy_detail_failed")
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": code,
                    "error_detail": "detail_fetch_or_parse_failed",
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue

        try:
            ingest_payload = vacancy_detail_to_ingest(detail["content"])
        except NormalizeError as error:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "page_parse_failed",
                    "error_detail": str(error),
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue

        try:
            ingest = client.ingest_vacancy(ingest_payload)
        except CoreError as error:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "core_ingest_failed",
                    "error_detail": str(error)[:1000],
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue

        outcome = str(ingest.get("outcome") or "")
        raw_vacancy = ingest.get("vacancy")
        vacancy: dict[str, Any] = raw_vacancy if isinstance(raw_vacancy, dict) else {}
        vacancy_id = vacancy.get("id")
        if outcome not in {"created", "updated", "unchanged"} or not vacancy_id:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "core_ingest_failed",
                    "error_detail": "invalid_ingest_result",
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue

        item_ok += 1
        item = _add_item(
            client,
            run_id,
            {
                "source_external_id": external_id,
                "outcome": outcome,
                "vacancy_id": vacancy_id,
                "page": page,
            },
        )
        recorded_items.append(
            item
            or {
                "source_external_id": external_id,
                "outcome": outcome,
                "vacancy_id": vacancy_id,
            }
        )

    base["items"] = recorded_items
    # pagination metadata (max_pages_reached / exhausted) lives on acquisition;
    # intentional max_pages bound alone is success, not partial.

    # Terminal status matrix.
    if ok_pages == 0 and (failed_pages > 0 or acquire_status in _BLOCKING_ACQUIRE):
        terminal = "failed"
        error_code = acquire_code or "search_page_failed"
    elif item_ok == 0 and item_errors == 0 and ok_pages > 0:
        # Valid empty result (or only empty pages within bound).
        terminal = "success"
        error_code = None
    elif item_errors > 0 or failed_pages > 0 or acquire_status == STATUS_PARTIAL:
        terminal = "partial"
        error_code = (
            acquire_code
            if acquire_status == STATUS_PARTIAL
            else ("partial_pagination" if failed_pages else "vacancy_detail_failed")
        )
    else:
        # Intentional max_pages bound is success, not partial.
        terminal = "success"
        error_code = None

    try:
        finalized = _finalize(
            client,
            run_id,
            status=terminal,
            error_code=error_code,
            recovery_hint=str((acquisition.get("recovery") or {}).get("kind") or "") or None,
        )
        base["search_run"] = finalized
    except CoreError as error:
        base["error"] = str(error)
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "search_run_finalize_failed",
            }
        )

    return with_recovery(
        {
            **base,
            "ok": terminal in {"success", "partial"},
            "status": terminal,
            "code": error_code or ("ready" if terminal == "success" else terminal),
            "action": acquisition.get("action") or {"code": "none"},
            "recovery": acquisition.get("recovery"),
        }
    )


def _candidate_context_for_active_resume(
    paths: SessionPaths, core: CoreClient
) -> dict[str, Any] | None:
    """Build provenance snapshot for the current active HH resume."""
    resumes = list_resumes(paths)
    raw_active = resumes.get("active_resume")
    active: dict[str, Any] | None = raw_active if isinstance(raw_active, dict) else None
    if not active or not active.get("external_id"):
        raw_selection = resumes.get("selection")
        selection: dict[str, Any] = raw_selection if isinstance(raw_selection, dict) else {}
        # Stale/missing active resume is not usable for primary acquisition.
        if selection.get("status") == "stale":
            return None
        stored = read_stored_external_id(paths)
        if not stored:
            return None
        active = {"external_id": stored, "title": None}
    context: dict[str, Any] = {
        "hh_resume_external_id": str(active["external_id"]),
        "hh_resume_title": active.get("title"),
    }
    try:
        cc = core.get_candidate_context()
        link = cc.get("hh_resume_link") if isinstance(cc, dict) else None
        resume_content = cc.get("resume_content") if isinstance(cc, dict) else None
        profile_version = cc.get("profile_version") if isinstance(cc, dict) else None
        if isinstance(resume_content, dict) and resume_content.get("resume_version_id"):
            context["resume_version_id"] = resume_content.get("resume_version_id")
        if isinstance(profile_version, dict) and profile_version.get("id"):
            context["profile_version_id"] = profile_version.get("id")
        if (
            isinstance(link, dict)
            and link.get("external_resume_id")
            and not context.get("hh_resume_title")
        ):
            context["hh_resume_title"] = link.get("title")
    except CoreError:
        pass
    return context


def _process_unique_items(
    client: CoreClient,
    run_id: str,
    *,
    summaries: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Ingest unique summaries; return (items, ok_count, error_count)."""
    item_errors = 0
    item_ok = 0
    seen: set[str] = set()
    recorded_items: list[dict[str, Any]] = []
    for summary in summaries:
        external_id = str(summary.get("external_id") or "").strip()
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        page = summary.get("source_page")
        detail = details.get(external_id)
        if (
            detail is None
            or str(detail.get("status")) != "ok"
            or not isinstance(detail.get("content"), dict)
        ):
            item_errors += 1
            code = str((detail or {}).get("code") or "vacancy_detail_failed")
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": code,
                    "error_detail": "detail_fetch_or_parse_failed",
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue
        try:
            ingest_payload = vacancy_detail_to_ingest(detail["content"])
        except NormalizeError as error:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "page_parse_failed",
                    "error_detail": str(error),
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue
        try:
            ingest = client.ingest_vacancy(ingest_payload)
        except CoreError as error:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "core_ingest_failed",
                    "error_detail": str(error)[:1000],
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue
        outcome = str(ingest.get("outcome") or "")
        raw_vacancy = ingest.get("vacancy")
        vacancy: dict[str, Any] = raw_vacancy if isinstance(raw_vacancy, dict) else {}
        vacancy_id = vacancy.get("id")
        if outcome not in {"created", "updated", "unchanged"} or not vacancy_id:
            item_errors += 1
            item = _add_item(
                client,
                run_id,
                {
                    "source_external_id": external_id,
                    "outcome": "error",
                    "vacancy_id": None,
                    "page": page,
                    "error_code": "core_ingest_failed",
                    "error_detail": "invalid_ingest_result",
                },
            )
            recorded_items.append(item or {"source_external_id": external_id, "outcome": "error"})
            continue
        item_ok += 1
        item = _add_item(
            client,
            run_id,
            {
                "source_external_id": external_id,
                "outcome": outcome,
                "vacancy_id": vacancy_id,
                "page": page,
            },
        )
        recorded_items.append(
            item
            or {
                "source_external_id": external_id,
                "outcome": outcome,
                "vacancy_id": vacancy_id,
            }
        )
    return recorded_items, item_ok, item_errors


def run_resume_suitable_search(
    *,
    max_pages: int = 1,
    order: str = "publication_time",
    core: CoreClient | None = None,
    paths: SessionPaths | None = None,
    page_reader: VacancyPagesReader | None = None,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Primary UJM flow: active resume → suitable SERP → ingest → finalize."""
    settings = Settings.from_env()
    client = core or CoreClient(settings.core_url, settings.timeout_seconds)
    resolved = paths or SessionPaths.from_env()
    checked_at = _utc_now()
    base: dict[str, Any] = {
        "operation": "resume_suitable_search_run",
        "checked_at": checked_at,
        "search_profile_id": None,
        "acquisition_kind": "resume_suitable",
        "search_run": None,
        "acquisition": None,
        "items": [],
        "hh_writes": False,
        "action": {"code": "none"},
        "source_total": None,
    }

    context = _candidate_context_for_active_resume(resolved, client)
    if context is None:
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "active_resume_required",
                "error": "no_active_hh_resume",
            }
        )
    resume_id = str(context["hh_resume_external_id"])
    base["candidate_context"] = {
        "hh_resume_external_id": resume_id,
        "hh_resume_title": context.get("hh_resume_title"),
    }

    execution = {
        "order": order or "publication_time",
        "max_pages": max(1, min(int(max_pages), 20)),
        "transport": "browser",
        "discovery": "resume_suitable",
    }
    try:
        run = client.start_search_run(
            search_profile_id=None,
            acquisition_kind="resume_suitable",
            execution=execution,
            candidate_context_snapshot=context,
        )
    except CoreError as error:
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "search_run_start_failed",
                "error": str(error),
            }
        )

    run_id = str(run.get("id") or "")
    base["search_run"] = {"id": run_id, "status": run.get("status")}
    policy = ExecutionPolicy(
        order=str(execution["order"]),
        max_pages=int(str(execution["max_pages"])),
        page_size=None,
    )

    def page_url_builder(page: int) -> str:
        return map_resume_suitable_query(resume_id, page=page, order=str(execution["order"])).url

    def serp_guard(*, final_url: str, found_text: str | None, card_count: int) -> dict[str, Any]:
        return validate_resume_suitable_page(
            expected_resume_id=resume_id,
            final_url=final_url,
            found_text=found_text,
            card_count=card_count,
        )

    try:
        acquisition = acquire_vacancies(
            SearchCriteria(),  # not used for URL when page_url_builder is set
            policy,
            paths=resolved,
            page_reader=page_reader,
            fetch_details=True,
            detail_limit=200,
            timeout_seconds=timeout_seconds,
            page_url_builder=page_url_builder,
            serp_guard=serp_guard,
        )
    except Exception as error:  # noqa: BLE001
        try:
            finalized = _finalize(
                client,
                run_id,
                status="failed",
                error_code="transport_unavailable",
                recovery_hint=type(error).__name__,
            )
            base["search_run"] = finalized
        except CoreError:
            pass
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "transport_unavailable",
                "error": type(error).__name__,
            }
        )

    base["acquisition"] = {
        "status": acquisition.get("status"),
        "code": acquisition.get("code"),
        "pagination": acquisition.get("pagination"),
        "recovery": acquisition.get("recovery"),
        "serp_guard": acquisition.get("serp_guard"),
    }
    source_total: int | None = None
    raw_pagination = acquisition.get("pagination")
    page_meta: dict[str, Any] = dict(raw_pagination) if isinstance(raw_pagination, dict) else {}
    raw_total = page_meta.get("source_total")
    if raw_total is not None:
        try:
            source_total = int(str(raw_total))
        except (TypeError, ValueError):
            source_total = None
    base["source_total"] = source_total

    acquire_status = str(acquisition.get("status") or "")
    acquire_code = str(acquisition.get("code") or "")
    pages = [p for p in list(acquisition.get("pages") or []) if isinstance(p, dict)]
    ok_pages = sum(1 for p in pages if str(p.get("status")) == "ok")
    failed_pages = sum(1 for p in pages if str(p.get("status")) != "ok")

    if acquire_code == "resume_search_page_mismatch" or (
        acquire_status in _BLOCKING_ACQUIRE and ok_pages == 0
    ):
        try:
            finalized = _finalize(
                client,
                run_id,
                status="failed",
                error_code=acquire_code or "search_page_failed",
                recovery_hint=str((acquisition.get("recovery") or {}).get("kind") or ""),
                source_total=source_total,
            )
            base["search_run"] = finalized
        except CoreError as error:
            base["error"] = str(error)
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": acquire_code or "search_page_failed",
                "action": acquisition.get("action") or {"code": "none"},
                "recovery": acquisition.get("recovery"),
            }
        )

    summaries = [s for s in list(acquisition.get("summaries") or []) if isinstance(s, dict)]
    details = _detail_map(
        [d for d in list(acquisition.get("details") or []) if isinstance(d, dict)]
    )
    recorded_items, item_ok, item_errors = _process_unique_items(
        client, run_id, summaries=summaries, details=details
    )
    base["items"] = recorded_items

    if ok_pages == 0 and (failed_pages > 0 or acquire_status in _BLOCKING_ACQUIRE):
        terminal = "failed"
        error_code = acquire_code or "search_page_failed"
    elif item_ok == 0 and item_errors == 0 and ok_pages > 0:
        terminal = "success"
        error_code = None
    elif item_errors > 0 or failed_pages > 0 or acquire_status == STATUS_PARTIAL:
        terminal = "partial"
        error_code = (
            acquire_code
            if acquire_status == STATUS_PARTIAL
            else ("partial_pagination" if failed_pages else "vacancy_detail_failed")
        )
    else:
        terminal = "success"
        error_code = None

    try:
        finalized = _finalize(
            client,
            run_id,
            status=terminal,
            error_code=error_code,
            recovery_hint=str((acquisition.get("recovery") or {}).get("kind") or "") or None,
            source_total=source_total,
        )
        base["search_run"] = finalized
    except CoreError as error:
        base["error"] = str(error)
        return with_recovery(
            {
                **base,
                "ok": False,
                "status": "failed",
                "code": "search_run_finalize_failed",
            }
        )

    return with_recovery(
        {
            **base,
            "ok": terminal in {"success", "partial"},
            "status": terminal,
            "code": error_code or ("ready" if terminal == "success" else terminal),
            "action": acquisition.get("action") or {"code": "none"},
            "recovery": acquisition.get("recovery"),
        }
    )
