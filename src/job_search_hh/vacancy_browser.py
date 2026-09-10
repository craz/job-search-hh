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
    looks_like_hh_challenge,
    normalize_detail_payload,
    normalize_search_payload,
)
from job_search_hh.vacancy_query import (
    MAX_START_PAGE,
    ExecutionPolicy,
    QueryMapping,
    SearchCriteria,
    map_search_query,
)

DEFAULT_VACANCY_URL_TEMPLATE = "https://hh.ru/vacancy/{external_id}"
TRANSPORT = "browser_readonly"


def _detail_failure_code(error: BaseException) -> str:
    """Map detail-page exceptions to stable codes (never pretend SyntaxError is network)."""
    transport = classify_browser_transport_error(error)
    if transport:
        return transport
    message = str(error)
    low = message.casefold()
    if (
        "already been declared" in low
        or "syntaxerror" in low
        or "page.evaluate" in low
        or "identifier '" in low
    ):
        return "page_extract_failed"
    if "timeout" in low or "err_timed_out" in low:
        return "vacancy_detail_failed"
    # Chromium net errors that are not proxy-specific still stay detail-failed
    # (recovery maps vacancy_detail_failed → network_failure).
    if "net::err_" in low or "ns_error_" in low:
        return "vacancy_detail_failed"
    return "vacancy_detail_failed"


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


def _screenshot_flag(raw: dict[str, Any]) -> bool:
    shot = raw.get("screenshot")
    if not isinstance(shot, dict):
        return False
    return bool(shot.get("screenshot_available"))


def _finalize_captcha_handoff(
    raw: dict[str, Any],
    *,
    report: dict[str, Any],
    resolved: SessionPaths,
) -> dict[str, Any]:
    """Merge live-captured challenge evidence into the acquisition response.

    Screenshot/URL must already be captured in the page reader *before*
    ``context.close``. This step never fabricates a challenge URL and does not
    auto-open noVNC (owner must get interactive_ready from open-challenge).
    """
    from job_search_hh.challenge_handoff import begin_challenge_handoff

    challenge_url = str(raw.get("challenge_url") or "").strip()
    screenshot = raw.get("screenshot") if isinstance(raw.get("screenshot"), dict) else {}
    existing = raw.get("challenge") if isinstance(raw.get("challenge"), dict) else None
    pagination = report.get("pagination") if isinstance(report.get("pagination"), dict) else {}
    progress = {
        "pages_fetched": pagination.get("pages_fetched") or len(report.get("pages") or []),
        "pages_planned": pagination.get("max_pages"),
        "checked_count": len(report.get("summaries") or []),
        "phase": "captcha_required",
    }
    try:
        return begin_challenge_handoff(
            challenge_url=challenge_url,
            challenge_title=str(raw.get("challenge_title") or ""),
            vacancy_id=str(raw.get("wall_detail_id") or "") or None,
            progress=progress,
            screenshot=screenshot,
            paths=resolved,
            auto_open_browser=False,
            existing_state=existing,
        )
    except Exception:  # noqa: BLE001 - acquisition must still return captcha status
        recovery = bool(challenge_url)
        return {
            "action": (
                {
                    "code": "open_challenge",
                    "novnc_url": _novnc_url(),
                    "challenge_url": challenge_url,
                }
                if recovery
                else {
                    "code": "challenge_capture_failed",
                    "novnc_url": None,
                    "challenge_url": None,
                }
            ),
            "challenge": existing
            or {
                "screenshot_available": bool(screenshot.get("screenshot_available")),
                "screenshot_error": screenshot.get("screenshot_error"),
                "challenge_url": challenge_url or None,
                "challenge_session_available": False,
                "recovery_available": recovery,
                "capture_status": "captured" if recovery else "capture_failed",
            },
            "recovery_available": recovery,
        }


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
            "start_page": execution.start_page,
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
            "start_page": int(execution.start_page or 0),
            "page_from": int(execution.start_page or 0),
            "page_to": None,
            "next_page": None,
            "more_remaining": False,
            "exhausted": False,
            "max_pages_reached": False,
            "observed_page_size": None,
            "per_page": None,
            "found": None,
            "pages": None,
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
    on_page_progress: Callable[[dict[str, Any]], None] | None = None,
    detail_id_filter: Callable[[list[str]], list[str]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Open persistent Chromium profile and fetch SERP pages + optional details.

    When ``detail_id_filter`` is set (create-only), it receives unique SERP ids and
    must return the subset that still need HH detail fetches (typically NEW only).
    ``detail_ids`` is reserved for explicit allowlists; when non-empty it intersects
    the filtered set.
    """
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
    pages_planned = len(page_urls)
    page_from = page_urls[0][0] if page_urls else 0

    def _persist_captcha_before_close(
        page: Any,
        *,
        vacancy_id: str | None = None,
        challenge_url_hint: str | None = None,
        matched_signals: list[str] | None = None,
    ) -> dict[str, Any]:
        """Capture URL/title/PNG and write challenge_active before context.close.

        Uses the exact ``page`` the detector fired on (never pages[-1]).
        """
        from job_search_hh.challenge_handoff import capture_and_persist_live_challenge

        progress = {
            "pages_fetched": len(pages_out),
            "pages_planned": pages_planned,
            "page_from": page_from,
            "page_current": pages_out[-1]["page"] if pages_out else page_from,
            "checked_count": len(set(summaries_for_detail)),
            "phase": "captcha_required",
        }
        return capture_and_persist_live_challenge(
            page,
            challenge_url_hint=challenge_url_hint,
            run_id=run_id,
            vacancy_id=vacancy_id,
            progress=progress,
            matched_signals=matched_signals,
        )

    def _emit_page_progress(page_index: int) -> None:
        if on_page_progress is None:
            return
        seen: set[str] = set()
        source_total: int | None = None
        for page_info in pages_out:
            meta_obj = page_info.get("meta")
            meta: dict[str, Any] = meta_obj if isinstance(meta_obj, dict) else {}
            if source_total is None:
                for key in ("source_total", "found"):
                    raw_total = meta.get(key)
                    if isinstance(raw_total, int):
                        source_total = raw_total
                        break
                    if isinstance(raw_total, str) and raw_total.isdigit():
                        source_total = int(raw_total)
                        break
                if source_total is None and meta.get("found_text"):
                    digits = "".join(ch for ch in str(meta["found_text"]) if ch.isdigit())
                    if digits:
                        try:
                            source_total = int(digits)
                        except ValueError:
                            source_total = None
            for item in list(page_info.get("items") or []):
                if isinstance(item, dict) and item.get("external_id"):
                    seen.add(str(item["external_id"]))
        payload: dict[str, Any] = {
            "pages_fetched": len(pages_out),
            "pages_planned": pages_planned,
            "page_from": page_from,
            "page_current": page_index,
            "checked_count": len(seen),
            "phase": "serp",
        }
        if source_total is not None:
            payload["source_total"] = source_total
        try:
            on_page_progress(payload)
        except Exception:  # noqa: BLE001 - progress must not abort acquisition
            pass

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
                    _emit_page_progress(page_index)
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
                    wall_payload: dict[str, Any] = {
                        "kind": kind,
                        "pages": pages_out,
                        "details": details_out,
                        "wall_page": page_index,
                        "challenge_url": str(getattr(page, "url", "") or ""),
                    }
                    if kind == "captcha_or_action_required":
                        try:
                            meta_obj = normalized.get("meta") if isinstance(normalized, dict) else {}
                            serp_signals: list[str] = []
                            if isinstance(meta_obj, dict):
                                raw_sigs = meta_obj.get("matched_signals") or []
                                if isinstance(raw_sigs, list):
                                    serp_signals = [str(s) for s in raw_sigs if s]
                            evidence = _persist_captcha_before_close(
                                page,
                                challenge_url_hint=wall_payload["challenge_url"],
                                matched_signals=serp_signals,
                            )
                            if (
                                evidence.get("capture_status") == "captcha_capture_invalid"
                                or evidence.get("challenge_context_confirmed") is False
                            ):
                                # False/mismatched CAPTCHA evidence — do not wall the SERP run.
                                pages_out.append(
                                    {
                                        "page": page_index,
                                        "url": url,
                                        "status": "failed",
                                        "code": "captcha_evidence_invalid",
                                        "items": [],
                                        "meta": {"matched_signals": serp_signals},
                                    }
                                )
                                _emit_page_progress(page_index)
                                continue
                            wall_payload["challenge_url"] = evidence.get("challenge_url") or ""
                            wall_payload["challenge_title"] = evidence.get("challenge_title") or ""
                            wall_payload["screenshot"] = evidence.get("screenshot") or {
                                "screenshot_available": False
                            }
                            wall_payload["challenge"] = evidence.get("challenge")
                        except Exception:  # noqa: BLE001
                            wall_payload["screenshot"] = {
                                "screenshot_available": False,
                                "screenshot_error": "persist_failed",
                            }
                    return wall_payload
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
                _emit_page_progress(page_index)

            if fetch_details and summaries_for_detail:
                if on_page_progress is not None:
                    try:
                        on_page_progress(
                            {
                                "pages_fetched": len(pages_out),
                                "pages_planned": pages_planned,
                                "page_from": page_from,
                                "page_current": pages_out[-1]["page"] if pages_out else page_from,
                                "checked_count": len(set(summaries_for_detail)),
                                "phase": "details",
                            }
                        )
                    except Exception:  # noqa: BLE001
                        pass
                # Create-only: optionally drop ids Core already owns before detail work.
                unique_serp_ids: list[str] = list(dict.fromkeys(summaries_for_detail))
                allow = [str(x).strip() for x in (detail_ids or []) if str(x).strip()]
                candidate_ids = unique_serp_ids
                if allow:
                    allow_set = set(allow)
                    candidate_ids = [i for i in unique_serp_ids if i in allow_set]
                if detail_id_filter is not None:
                    try:
                        filtered = detail_id_filter(list(candidate_ids))
                    except Exception:  # noqa: BLE001 - fail open to no details rather than all
                        filtered = []
                    if not isinstance(filtered, list):
                        filtered = []
                    allowed_new = {str(x).strip() for x in filtered if str(x).strip()}
                    candidate_ids = [i for i in candidate_ids if i in allowed_new]
                limit = max(0, min(int(detail_limit), 1000))
                for detail_idx, external_id in enumerate(candidate_ids[:limit]):
                    detail_url = DEFAULT_VACANCY_URL_TEMPLATE.format(external_id=external_id)
                    try:
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=timeout_ms)
                        # Fail-fast on challenge URL/title before spending the full settle wait.
                        final_url = str(getattr(page, "url", "") or "")
                        page_title = ""
                        try:
                            page_title = str(page.title() or "")
                        except Exception:  # noqa: BLE001
                            page_title = ""
                        if looks_like_hh_challenge(url=final_url, title=page_title):
                            evidence: dict[str, Any] = {}
                            try:
                                from job_search_hh.vacancy_extractors import (
                                    diagnose_challenge_signals,
                                )

                                evidence = _persist_captcha_before_close(
                                    page,
                                    vacancy_id=external_id,
                                    challenge_url_hint=final_url,
                                    matched_signals=diagnose_challenge_signals(
                                        url=final_url, title=page_title
                                    ),
                                )
                            except Exception:  # noqa: BLE001
                                evidence = {
                                    "challenge_url": final_url,
                                    "challenge_title": page_title,
                                    "screenshot": {
                                        "screenshot_available": False,
                                        "screenshot_error": "persist_failed",
                                    },
                                }
                            if (
                                evidence.get("capture_status") == "captcha_capture_invalid"
                                or evidence.get("challenge_context_confirmed") is False
                            ):
                                details_out.append(
                                    {
                                        "external_id": external_id,
                                        "status": "failed",
                                        "code": "captcha_evidence_invalid",
                                        "content": None,
                                    }
                                )
                                continue
                            if on_page_progress is not None:
                                try:
                                    on_page_progress(
                                        {
                                            "pages_fetched": len(pages_out),
                                            "pages_planned": pages_planned,
                                            "page_from": page_from,
                                            "page_current": (
                                                pages_out[-1]["page"] if pages_out else page_from
                                            ),
                                            "checked_count": len(set(summaries_for_detail)),
                                            "phase": "captcha_required",
                                            "challenge_url": evidence.get("challenge_url")
                                            or final_url,
                                            "challenge_vacancy_id": external_id,
                                        }
                                    )
                                except Exception:  # noqa: BLE001
                                    pass
                            return {
                                "kind": "captcha_or_action_required",
                                "pages": pages_out,
                                "details": details_out,
                                "wall_detail_id": external_id,
                                "challenge_url": evidence.get("challenge_url") or final_url,
                                "challenge_title": evidence.get("challenge_title") or page_title,
                                "screenshot": evidence.get("screenshot")
                                or {"screenshot_available": False},
                                "challenge": evidence.get("challenge"),
                            }
                        page.wait_for_timeout(min(2_000, max(500, timeout_ms // 25)))
                        raw_detail = extract_detail_page(page)
                    except Exception as error:  # noqa: BLE001
                        details_out.append(
                            {
                                "external_id": external_id,
                                "status": "failed",
                                "code": _detail_failure_code(error),
                                "error": type(error).__name__,
                                "error_message": str(error)[:300],
                                "content": None,
                            }
                        )
                        if on_page_progress is not None and detail_idx % 10 == 9:
                            try:
                                on_page_progress(
                                    {
                                        "pages_fetched": len(pages_out),
                                        "pages_planned": pages_planned,
                                        "page_from": page_from,
                                        "page_current": (
                                            pages_out[-1]["page"] if pages_out else page_from
                                        ),
                                        "checked_count": len(set(summaries_for_detail)),
                                        "phase": "details",
                                    }
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        continue
                    kind = str((raw_detail or {}).get("kind") or "invalid")
                    if kind in {
                        "login_required",
                        "captcha_or_action_required",
                        "permission_blocked",
                    }:
                        if kind == "captcha_or_action_required" and on_page_progress is not None:
                            try:
                                meta = (
                                    (raw_detail or {}).get("meta")
                                    if isinstance(raw_detail, dict)
                                    else {}
                                )
                                challenge_url = ""
                                if isinstance(meta, dict):
                                    challenge_url = str(meta.get("challenge_url") or "")
                                on_page_progress(
                                    {
                                        "pages_fetched": len(pages_out),
                                        "pages_planned": pages_planned,
                                        "page_from": page_from,
                                        "page_current": (
                                            pages_out[-1]["page"] if pages_out else page_from
                                        ),
                                        "checked_count": len(set(summaries_for_detail)),
                                        "phase": "captcha_required",
                                        "challenge_url": challenge_url
                                        or str(getattr(page, "url", "") or ""),
                                        "challenge_vacancy_id": external_id,
                                    }
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        evidence: dict[str, Any] = {}
                        if kind == "captcha_or_action_required":
                            try:
                                meta = (
                                    (raw_detail or {}).get("meta")
                                    if isinstance(raw_detail, dict)
                                    else {}
                                )
                                hint = ""
                                signals: list[str] = []
                                if isinstance(meta, dict):
                                    hint = str(meta.get("challenge_url") or "")
                                    raw_signals = meta.get("matched_signals") or []
                                    if isinstance(raw_signals, list):
                                        signals = [str(s) for s in raw_signals if s]
                                evidence = _persist_captcha_before_close(
                                    page,
                                    vacancy_id=external_id,
                                    challenge_url_hint=hint or str(getattr(page, "url", "") or ""),
                                    matched_signals=signals,
                                )
                            except Exception:  # noqa: BLE001
                                evidence = {
                                    "challenge_url": str(getattr(page, "url", "") or ""),
                                    "screenshot": {
                                        "screenshot_available": False,
                                        "screenshot_error": "persist_failed",
                                    },
                                }
                            # Mismatched / false evidence → do not wall run as recoverable CAPTCHA.
                            if (
                                evidence.get("capture_status") == "captcha_capture_invalid"
                                or evidence.get("challenge_context_confirmed") is False
                            ):
                                details_out.append(
                                    {
                                        "external_id": external_id,
                                        "status": "failed",
                                        "code": "captcha_evidence_invalid",
                                        "content": None,
                                    }
                                )
                                continue
                        payload = {
                            "kind": kind,
                            "pages": pages_out,
                            "details": details_out,
                            "wall_detail_id": external_id,
                            "challenge_url": str(
                                evidence.get("challenge_url") or getattr(page, "url", "") or ""
                            ),
                        }
                        if evidence.get("challenge_title"):
                            payload["challenge_title"] = evidence["challenge_title"]
                        if evidence.get("screenshot"):
                            payload["screenshot"] = evidence["screenshot"]
                        if evidence.get("challenge"):
                            payload["challenge"] = evidence["challenge"]
                        return payload
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
                    if on_page_progress is not None and detail_idx % 10 == 9:
                        try:
                            on_page_progress(
                                {
                                    "pages_fetched": len(pages_out),
                                    "pages_planned": pages_planned,
                                    "page_from": page_from,
                                    "page_current": (
                                        pages_out[-1]["page"] if pages_out else page_from
                                    ),
                                    "checked_count": len(set(summaries_for_detail)),
                                    "phase": "details",
                                }
                            )
                        except Exception:  # noqa: BLE001
                            pass
        finally:
            context.close()

    return {"kind": "ok", "pages": pages_out, "details": details_out}


def _read_single_vacancy_detail(
    *,
    profile_dir: Any,
    vacancy_url: str,
    timeout_ms: int,
) -> dict[str, Any]:
    """Open persistent Chromium and extract one vacancy detail page (no SERP).

    Reuses ``extract_detail_page`` / ``normalize_detail_payload``. Returns a
    wall ``kind`` without content, or ``kind=ok`` with allowlisted content.
    Does not write to HH or Core.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover
        raise SessionError("playwright_missing") from error

    display = (os.getenv("DISPLAY") or os.getenv("HH_DISPLAY") or "").strip()
    env: dict[str, str | float | bool] = {key: value for key, value in os.environ.items()}
    if display:
        env["DISPLAY"] = display

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            env=env if display else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(vacancy_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(2_000, max(500, timeout_ms // 25)))
            raw_detail = extract_detail_page(page)
        finally:
            context.close()

    if not isinstance(raw_detail, dict):
        return {"kind": "invalid", "content": None}

    kind = str(raw_detail.get("kind") or "invalid")
    if kind in {
        "login_required",
        "captcha_or_action_required",
        "permission_blocked",
    }:
        return {"kind": kind, "content": None}

    normalized = normalize_detail_payload(raw_detail)
    return {
        "kind": str(normalized.get("kind") or "invalid"),
        "content": normalized.get("content"),
    }


def _finalize_pagination_meta(
    pagination: dict[str, Any],
    *,
    start_page: int,
    pages_fetched: int,
    max_pages: int,
    exhausted: bool,
    observed_sizes: list[int],
) -> dict[str, Any]:
    """Attach HH-style found/pages/continuation fields from observed SERP metadata."""
    observed = observed_sizes[0] if observed_sizes else None
    page_to = start_page + pages_fetched - 1 if pages_fetched else None
    absolute_next = start_page + pages_fetched
    source_total = pagination.get("source_total")
    if source_total is None:
        source_total = pagination.get("found")
    pages_total: int | None = None
    more_remaining = False
    if isinstance(source_total, int) and observed and observed > 0:
        pages_total = (int(source_total) + observed - 1) // observed
        more_remaining = (not exhausted) and absolute_next < pages_total
    elif not exhausted and pages_fetched >= max_pages and observed_sizes and observed_sizes[-1] > 0:
        more_remaining = True
    pagination.update(
        {
            "start_page": start_page,
            "page_from": start_page,
            "page_to": page_to,
            "next_page": absolute_next if more_remaining else None,
            "more_remaining": more_remaining,
            "observed_page_size": observed,
            "per_page": observed,
            "found": source_total if isinstance(source_total, int) else pagination.get("found"),
            "pages": pages_total,
        }
    )
    return pagination


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
    on_page_progress: Callable[[dict[str, Any]], None] | None = None,
    detail_id_filter: Callable[[list[str]], list[str]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Bounded list-first vacancy acquisition via browser RO transport."""
    resolved = paths or SessionPaths.from_env()
    policy = execution or ExecutionPolicy()
    max_pages = max(1, min(int(policy.max_pages), 20))
    try:
        start_page = int(policy.start_page or 0)
    except (TypeError, ValueError):
        start_page = 0
    start_page = max(0, min(start_page, MAX_START_PAGE))
    policy = ExecutionPolicy(
        order=policy.order,
        max_pages=max_pages,
        start_page=start_page,
        page_size=policy.page_size,
    )
    page_indexes = list(range(start_page, start_page + max_pages))
    if page_url_builder is not None:
        first_url = page_url_builder(start_page)
        first_map = QueryMapping(url=first_url, query={}, unsupported=[], page_size_note=None)
        page_urls = [(index, page_url_builder(index)) for index in page_indexes]
    else:
        first_map = map_search_query(criteria, policy, page=start_page)
        page_urls = [
            (index, map_search_query(criteria, policy, page=index).url) for index in page_indexes
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
            reader_kwargs: dict[str, Any] = {
                "profile_dir": resolved.profile_dir,
                "page_urls": page_urls,
                "detail_ids": [],
                "timeout_ms": int(timeout_seconds * 1000),
                "fetch_details": bool(fetch_details),
                "detail_limit": max(0, min(int(detail_limit), 1000)),
            }
            if on_page_progress is not None:
                reader_kwargs["on_page_progress"] = on_page_progress
            if run_id:
                reader_kwargs["run_id"] = run_id
            if detail_id_filter is not None:
                reader_kwargs["detail_id_filter"] = detail_id_filter
            raw = reader(**reader_kwargs)
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
    report["detail_requests"] = len(details)
    report["serp_ids"] = [str(s.get("external_id") or "") for s in summaries]

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
        handoff = _finalize_captcha_handoff(raw, report=report, resolved=resolved)
        return with_recovery(
            {
                **report,
                "status": STATUS_ACTION_REQUIRED,
                "code": "browser_captcha_or_action_required",
                "action": handoff.get("action")
                or {"code": "challenge_capture_failed", "novnc_url": None},
                "challenge_url": raw.get("challenge_url") or None,
                "challenge": handoff.get("challenge"),
                "screenshot_available": _screenshot_flag(raw),
                "recovery_available": bool(handoff.get("recovery_available")),
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
    _finalize_pagination_meta(
        pagination,
        start_page=start_page,
        pages_fetched=pages_fetched,
        max_pages=max_pages,
        exhausted=exhausted,
        observed_sizes=observed_sizes,
    )
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
        handoff = _finalize_captcha_handoff(raw, report=report, resolved=resolved)
        return with_recovery(
            {
                **report,
                "status": STATUS_ACTION_REQUIRED,
                "code": "browser_captcha_or_action_required",
                "action": handoff.get("action")
                or {"code": "challenge_capture_failed", "novnc_url": None},
                "challenge_url": raw.get("challenge_url") or None,
                "wall_detail_id": raw.get("wall_detail_id"),
                "challenge": handoff.get("challenge"),
                "screenshot_available": _screenshot_flag(raw),
                "recovery_available": bool(handoff.get("recovery_available")),
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
            _finalize_pagination_meta(
                pagination,
                start_page=start_page,
                pages_fetched=pages_fetched,
                max_pages=max_pages,
                exhausted=exhausted,
                observed_sizes=observed_sizes,
            )
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
