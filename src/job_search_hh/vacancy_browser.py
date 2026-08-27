"""Browser read-only HH vacancy acquisition (R2.2.2).

Explicit transport: Chromium persistent profile navigation of public search /
vacancy pages. Does **not** fall back from official API, does **not** write to
HH or Core, and never bypasses login/CAPTCHA walls.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from job_search_hh.connection import connection_status
from job_search_hh.egress import classify_browser_transport_error, egress_diagnostic
from job_search_hh.recovery import with_recovery
from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    novnc_public_url,
)
from job_search_hh.vacancy_dto import HhVacancySummary
from job_search_hh.vacancy_extractors import (
    EXTRACTOR_VERSION,
    extract_detail_page,
    extract_search_page,
    normalize_detail_payload,
    normalize_search_payload,
)
from job_search_hh.vacancy_query import (
    ExecutionPolicy,
    QueryMapping,
    SearchCriteria,
    map_search_query,
)

DEFAULT_VACANCY_URL_TEMPLATE = "https://hh.ru/vacancy/{external_id}"
TRANSPORT = "browser_readonly"

STATUS_AVAILABLE = "available"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_PERMISSION_BLOCKED = "permission_blocked"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ACTION_REQUIRED = "action_required"
STATUS_PARTIAL = "partial"

VacancyPagesReader = Callable[..., dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _novnc_url() -> str:
    return novnc_public_url()


def _base_report(
    *,
    criteria: SearchCriteria,
    execution: ExecutionPolicy,
    mapping: QueryMapping,
) -> dict[str, Any]:
    return {
        "transport": TRANSPORT,
        "extractor_version": EXTRACTOR_VERSION,
        "checked_at": _utc_now(),
        "criteria": {
            "text": criteria.text,
            "area": criteria.area,
            "salary": criteria.salary,
            "experience": criteria.experience,
            "employment": criteria.employment,
            "schedule": criteria.schedule,
            "search_field": criteria.search_field,
            "only_with_salary": criteria.only_with_salary,
        },
        "execution": {
            "order": execution.order,
            "max_pages": execution.max_pages,
            "page_size": execution.page_size,
            "page_size_note": mapping.page_size_note,
        },
        "unsupported_mapping": list(mapping.unsupported),
        "search_url_template": mapping.url.replace(
            f"page={mapping.query.get('page', '0')}", "page={page}"
        )
        if "page=" in mapping.url
        else mapping.url,
        "pages": [],
        "summaries": [],
        "details": [],
        "pagination": {
            "pages_fetched": 0,
            "max_pages": max(1, execution.max_pages),
            "exhausted": False,
            "max_pages_reached": False,
            "observed_page_size": None,
            "found_text": None,
            "partial": False,
        },
        "action": {"code": "none"},
        "hh_writes": False,
        "core_ingestion": False,
    }


def _read_vacancy_pages(
    *,
    profile_dir: Any,
    page_urls: list[tuple[int, str]],
    detail_ids: list[str],
    timeout_ms: int,
    fetch_details: bool = False,
    detail_limit: int = 0,
) -> dict[str, Any]:
    """Open persistent Chromium profile and fetch SERP pages + optional details."""
    del detail_ids  # ids chosen from summaries inside one session
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover
        raise SessionError("playwright_missing") from error

    display = (os.getenv("DISPLAY") or os.getenv("HH_DISPLAY") or "").strip()
    env: dict[str, str | float | bool] = {key: value for key, value in os.environ.items()}
    if display:
        env["DISPLAY"] = display

    pages_out: list[dict[str, Any]] = []
    details_out: list[dict[str, Any]] = []
    summaries_for_detail: list[str] = []

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            env=env if display else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for page_index, url in page_urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(min(2_500, max(500, timeout_ms // 20)))
                    raw = extract_search_page(page)
                except Exception as error:  # noqa: BLE001 - surface as page failure
                    pages_out.append(
                        {
                            "page": page_index,
                            "url": url,
                            "status": "failed",
                            "code": "search_page_failed",
                            "error": type(error).__name__,
                            "items": [],
                            "meta": {},
                        }
                    )
                    continue
                normalized = normalize_search_payload(
                    raw if isinstance(raw, dict) else {},
                    page=page_index,
                    source_url=url,
                )
                kind = str(normalized.get("kind") or "invalid")
                if kind in {
                    "login_required",
                    "captcha_or_action_required",
                    "permission_blocked",
                }:
                    return {
                        "kind": kind,
                        "pages": pages_out,
                        "details": details_out,
                        "wall_page": page_index,
                    }
                status = "ok" if kind in {"ok", "empty"} else "failed"
                code = (
                    "ready"
                    if kind == "ok"
                    else ("empty" if kind == "empty" else "page_parse_failed")
                )
                items = list(normalized.get("items") or [])
                pages_out.append(
                    {
                        "page": page_index,
                        "url": url,
                        "status": status,
                        "code": code,
                        "items": items,
                        "meta": normalized.get("meta") or {},
                    }
                )
                for item in items:
                    if isinstance(item, dict) and item.get("external_id"):
                        summaries_for_detail.append(str(item["external_id"]))

            if fetch_details and summaries_for_detail:
                limit = max(0, min(int(detail_limit), 200))
                for external_id in summaries_for_detail[:limit]:
                    detail_url = DEFAULT_VACANCY_URL_TEMPLATE.format(external_id=external_id)
                    try:
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=timeout_ms)
                        page.wait_for_timeout(min(2_000, max(500, timeout_ms // 25)))
                        raw_detail = extract_detail_page(page)
                    except Exception as error:  # noqa: BLE001
                        details_out.append(
                            {
                                "external_id": external_id,
                                "status": "failed",
                                "code": "vacancy_detail_failed",
                                "error": type(error).__name__,
                                "content": None,
                            }
                        )
                        continue
                    kind = str((raw_detail or {}).get("kind") or "invalid")
                    if kind in {
                        "login_required",
                        "captcha_or_action_required",
                        "permission_blocked",
                    }:
                        return {
                            "kind": kind,
                            "pages": pages_out,
                            "details": details_out,
                            "wall_detail_id": external_id,
                        }
                    normalized_detail = normalize_detail_payload(
                        raw_detail if isinstance(raw_detail, dict) else {}
                    )
                    if normalized_detail.get("kind") == "ok":
                        details_out.append(
                            {
                                "external_id": external_id,
                                "status": "ok",
                                "code": "ready",
                                "content": normalized_detail.get("content"),
                            }
                        )
                    else:
                        details_out.append(
                            {
                                "external_id": external_id,
                                "status": "failed",
                                "code": "page_parse_failed",
                                "content": None,
                            }
                        )
        finally:
            context.close()

    return {"kind": "ok", "pages": pages_out, "details": details_out}


def acquire_vacancies(
    criteria: SearchCriteria,
    execution: ExecutionPolicy | None = None,
    *,
    paths: SessionPaths | None = None,
    page_reader: VacancyPagesReader | None = None,
    fetch_details: bool = True,
    detail_limit: int = 1,
    timeout_seconds: float = 60.0,
    page_url_builder: Callable[[int], str] | None = None,
    serp_guard: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bounded list-first vacancy acquisition via browser RO transport."""
    resolved = paths or SessionPaths.from_env()
    policy = execution or ExecutionPolicy()
    max_pages = max(1, min(int(policy.max_pages), 20))
    policy = ExecutionPolicy(
        order=policy.order,
        max_pages=max_pages,
        page_size=policy.page_size,
    )
    if page_url_builder is not None:
        first_url = page_url_builder(0)
        first_map = QueryMapping(url=first_url, query={}, unsupported=[], page_size_note=None)
        page_urls = [(index, page_url_builder(index)) for index in range(max_pages)]
    else:
        first_map = map_search_query(criteria, policy, page=0)
        page_urls = [
            (index, map_search_query(criteria, policy, page=index).url)
            for index in range(max_pages)
        ]
    report = _base_report(criteria=criteria, execution=policy, mapping=first_map)
    report["connection_status"] = str(
        (connection_status(resolved) or {}).get("status") or STATUS_UNAVAILABLE
    )
    auth = auth_status(resolved)
    report["login_ready"] = bool(auth.get("login_ready"))

    if not auth.get("login_ready"):
        return with_recovery(
            {
                **report,
                "status": STATUS_NOT_AUTHORIZED,
                "code": "browser_login_required",
                "action": {"code": "open_login", "novnc_url": _novnc_url()},
            }
        )

    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return with_recovery(
            {
                **report,
                "status": STATUS_UNAVAILABLE,
                "code": "profile_locked",
                "action": {"code": "confirm_login", "novnc_url": _novnc_url()},
            }
        )

    reader = page_reader or _read_vacancy_pages

    try:
        lock.acquire("vacancy-browser-ro")
        try:
            raw = reader(
                profile_dir=resolved.profile_dir,
                page_urls=page_urls,
                detail_ids=[],
                timeout_ms=int(timeout_seconds * 1000),
                fetch_details=bool(fetch_details),
                detail_limit=max(0, min(int(detail_limit), 200)),
            )
        finally:
            lock.release()
    except SessionError as error:
        return with_recovery(
            {
                **report,
                "status": STATUS_UNAVAILABLE,
                "code": str(error) or "transport_unavailable",
            }
        )
    except Exception as error:
        code = classify_browser_transport_error(error) or "browser_vacancy_read_failed"
        payload: dict[str, Any] = {
            **report,
            "status": STATUS_UNAVAILABLE,
            "code": code,
        }
        if code == "browser_proxy_unavailable":
            payload["egress"] = egress_diagnostic()
        return with_recovery(payload)

    if not isinstance(raw, dict):
        return with_recovery(
            {
                **report,
                "status": STATUS_UNAVAILABLE,
                "code": "invalid_vacancy_page",
            }
        )

    wall = str(raw.get("kind") or "")
    pages = [p for p in list(raw.get("pages") or []) if isinstance(p, dict)]
    summaries: list[HhVacancySummary] = []
    seen_ids: set[str] = set()
    failed_pages = 0
    ok_pages = 0
    observed_sizes: list[int] = []
    found_text: str | None = None
    exhausted = False

    for page_info in pages:
        report["pages"].append(page_info)
        status = str(page_info.get("status") or "")
        if status == "ok":
            ok_pages += 1
        else:
            failed_pages += 1
        items_obj = page_info.get("items")
        items_list: list[Any] = items_obj if isinstance(items_obj, list) else []
        meta_obj = page_info.get("meta")
        meta: dict[str, Any] = meta_obj if isinstance(meta_obj, dict) else {}
        if found_text is None and meta.get("found_text"):
            found_text = str(meta.get("found_text"))
        if status == "ok":
            observed_sizes.append(len(items_list))
            if len(items_list) == 0:
                exhausted = True
        for item in items_list:
            if not isinstance(item, dict):
                continue
            external_id = str(item.get("external_id") or "")
            if not external_id or external_id in seen_ids:
                continue
            seen_ids.add(external_id)
            summaries.append(item)  # type: ignore[arg-type]

    details = [d for d in list(raw.get("details") or []) if isinstance(d, dict)]
    report["summaries"] = summaries
    report["details"] = details

    if wall == "login_required" and ok_pages == 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_NOT_AUTHORIZED,
                "code": "browser_session_not_logged_in",
                "action": {"code": "open_login", "novnc_url": _novnc_url()},
            }
        )
    if wall == "captcha_or_action_required" and ok_pages == 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_ACTION_REQUIRED,
                "code": "browser_captcha_or_action_required",
                "action": {"code": "confirm_login", "novnc_url": _novnc_url()},
            }
        )
    if wall == "permission_blocked" and ok_pages == 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_PERMISSION_BLOCKED,
                "code": "browser_vacancy_forbidden",
            }
        )

    pages_fetched = len(pages)
    max_pages_reached = pages_fetched >= max_pages and not exhausted
    if ok_pages and observed_sizes and observed_sizes[-1] == 0:
        exhausted = True
    partial = (failed_pages > 0 and ok_pages > 0) or wall in {
        "login_required",
        "captcha_or_action_required",
        "permission_blocked",
    }
    detail_failures = sum(1 for d in details if str(d.get("status")) != "ok")
    if detail_failures > 0 and (ok_pages > 0 or summaries):
        partial = True

    pagination = {
        "pages_fetched": pages_fetched,
        "max_pages": max_pages,
        "exhausted": exhausted,
        "max_pages_reached": bool(max_pages_reached and not exhausted),
        "observed_page_size": observed_sizes[0] if observed_sizes else None,
        "found_text": found_text,
        "partial": partial or detail_failures > 0,
        "failed_pages": failed_pages,
        "detail_failures": detail_failures,
    }
    report["pagination"] = pagination

    if wall == "login_required":
        return with_recovery(
            {
                **report,
                "status": STATUS_PARTIAL,
                "code": "browser_session_not_logged_in",
                "action": {"code": "open_login", "novnc_url": _novnc_url()},
            }
        )
    if wall == "captcha_or_action_required":
        return with_recovery(
            {
                **report,
                "status": STATUS_PARTIAL,
                "code": "browser_captcha_or_action_required",
                "action": {"code": "confirm_login", "novnc_url": _novnc_url()},
            }
        )
    if wall == "permission_blocked":
        return with_recovery(
            {
                **report,
                "status": STATUS_PARTIAL,
                "code": "browser_vacancy_forbidden",
            }
        )

    if ok_pages == 0 and failed_pages > 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_UNAVAILABLE,
                "code": "search_page_failed",
            }
        )
    if ok_pages == 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_UNAVAILABLE,
                "code": "page_parse_failed",
            }
        )

    if serp_guard is not None:
        first_ok = next((p for p in pages if str(p.get("status")) == "ok"), {})
        raw_first_items = first_ok.get("items")
        first_items: list[Any] = raw_first_items if isinstance(raw_first_items, list) else []
        guard_result = serp_guard(
            final_url=str(first_ok.get("url") or first_map.url),
            found_text=found_text,
            card_count=len(first_items),
        )
        report["serp_guard"] = guard_result
        if not isinstance(guard_result, dict) or not guard_result.get("ok"):
            report["summaries"] = []
            report["details"] = []
            return with_recovery(
                {
                    **report,
                    "status": STATUS_UNAVAILABLE,
                    "code": str((guard_result or {}).get("code") or "resume_search_page_mismatch"),
                }
            )
        if guard_result.get("source_total") is not None:
            pagination["source_total"] = guard_result.get("source_total")
            report["pagination"] = pagination

    if partial or detail_failures > 0:
        return with_recovery(
            {
                **report,
                "status": STATUS_PARTIAL,
                "code": "partial_pagination" if failed_pages else "vacancy_detail_failed",
            }
        )
    if not summaries:
        return with_recovery(
            {
                **report,
                "status": STATUS_AVAILABLE,
                "code": "empty",
            }
        )
    return with_recovery(
        {
            **report,
            "status": STATUS_AVAILABLE,
            "code": "ready",
        }
    )


class BrowserHhVacancyProvider:
    """Explicit browser RO vacancy provider (supported R2.2.2 transport)."""

    transport = TRANSPORT

    def acquire(
        self,
        criteria: SearchCriteria,
        execution: ExecutionPolicy | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return acquire_vacancies(criteria, execution, **kwargs)
