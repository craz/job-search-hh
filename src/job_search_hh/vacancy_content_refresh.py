"""Manual owner-triggered HH vacancy content refresh (create-only complement).

Fetches one HH detail page and upserts via Core ingest. Intended for the
explicit Web action «Проверить обновления» — never for batch acquisition or
automation sweeps. Does not mutate Assessment history, owner_decision,
Application, DirectOutreach, HiringProcess, or Offer (Core ingest preserves
user-owned fields). Does not enqueue Scoring.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient, CoreError
from job_search_hh.egress import classify_browser_transport_error, egress_diagnostic
from job_search_hh.normalize import NormalizeError, vacancy_detail_to_ingest
from job_search_hh.recovery import with_recovery
from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    novnc_public_url,
)
from job_search_hh.vacancy_browser import (
    DEFAULT_VACANCY_URL_TEMPLATE,
    STATUS_ACTION_REQUIRED,
    STATUS_AVAILABLE,
    STATUS_NOT_AUTHORIZED,
    STATUS_PERMISSION_BLOCKED,
    STATUS_UNAVAILABLE,
    TRANSPORT,
    _read_single_vacancy_detail,
)
from job_search_hh.vacancy_extractors import EXTRACTOR_VERSION

VacancyDetailReader = Callable[..., dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _novnc_url() -> str:
    return novnc_public_url()


def refresh_vacancy_content(
    external_id: str,
    *,
    paths: SessionPaths | None = None,
    core: CoreClient | None = None,
    page_reader: VacancyDetailReader | None = None,
    timeout_seconds: float = 45.0,
    vacancy_url_template: str = DEFAULT_VACANCY_URL_TEMPLATE,
) -> dict[str, Any]:
    """Fetch one HH vacancy detail and ingest into Core (updated|unchanged|created).

    UX statuses:
    - ``unchanged`` → «Изменений нет»
    - ``updated`` / ``created`` → «Вакансия обновлена»
    - ``unavailable`` → «Вакансия недоступна на HH»
    - ``error`` → «Не удалось проверить»
    """
    resolved = paths or SessionPaths.from_env()
    settings = Settings.from_env()
    client = core or CoreClient(settings.core_url, settings.timeout_seconds)
    checked_at = _utc_now()
    eid = (external_id or "").strip()
    base: dict[str, Any] = {
        "operation": "vacancy_content_refresh",
        "external_id": eid,
        "checked_at": checked_at,
        "transport": TRANSPORT,
        "extractor_version": EXTRACTOR_VERSION,
        "hh_writes": False,
        "core_writes": True,
        "scoring_enqueued": False,
        "outcome": None,
        "vacancy": None,
        "ux_status": "error",
        "action": {"code": "none"},
    }

    def fail(
        *,
        ux_status: str,
        code: str,
        transport_status: str = STATUS_UNAVAILABLE,
        action: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            **base,
            "ok": False,
            "status": transport_status,
            "ux_status": ux_status,
            "code": code,
            "action": action or {"code": "none"},
        }
        if extra:
            payload.update(extra)
        return with_recovery(payload)

    if not eid or not eid.isdigit():
        return fail(ux_status="error", code="invalid_vacancy_id")

    auth = auth_status(resolved)
    if not auth.get("login_ready"):
        return fail(
            ux_status="error",
            code="browser_login_required",
            transport_status=STATUS_NOT_AUTHORIZED,
            action={"code": "open_login", "novnc_url": _novnc_url()},
        )

    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return fail(
            ux_status="error",
            code="profile_locked",
            action={"code": "confirm_login", "novnc_url": _novnc_url()},
        )

    vacancy_url = vacancy_url_template.format(external_id=eid)
    reader = page_reader or _read_single_vacancy_detail
    try:
        lock.acquire("vacancy-content-refresh")
        try:
            raw = reader(
                profile_dir=resolved.profile_dir,
                vacancy_url=vacancy_url,
                timeout_ms=int(timeout_seconds * 1000),
            )
        finally:
            lock.release()
    except SessionError as error:
        return fail(ux_status="error", code=str(error) or "transport_unavailable")
    except Exception as error:  # noqa: BLE001
        code = classify_browser_transport_error(error) or "browser_vacancy_read_failed"
        extra = {"egress": egress_diagnostic()} if code == "browser_proxy_unavailable" else None
        return fail(ux_status="error", code=code, extra=extra)

    if not isinstance(raw, dict):
        return fail(ux_status="error", code="invalid_vacancy_page")

    kind = str(raw.get("kind") or "")
    if kind == "login_required":
        return fail(
            ux_status="error",
            code="browser_session_not_logged_in",
            transport_status=STATUS_NOT_AUTHORIZED,
            action={"code": "open_login", "novnc_url": _novnc_url()},
        )
    if kind == "captcha_or_action_required":
        return fail(
            ux_status="error",
            code="browser_captcha_or_action_required",
            transport_status=STATUS_ACTION_REQUIRED,
            action={"code": "confirm_login", "novnc_url": _novnc_url()},
        )
    if kind == "permission_blocked":
        return fail(
            ux_status="unavailable",
            code="browser_vacancy_forbidden",
            transport_status=STATUS_PERMISSION_BLOCKED,
        )
    if kind != "ok":
        # Missing / gone pages typically surface as invalid/parse failure.
        return fail(
            ux_status="unavailable" if kind in {"invalid", "empty"} else "error",
            code="page_parse_failed" if kind == "invalid" else "vacancy_detail_failed",
        )

    content_obj = raw.get("content")
    content: dict[str, Any] = content_obj if isinstance(content_obj, dict) else {}
    if not content.get("external_id") or not content.get("title"):
        return fail(ux_status="unavailable", code="page_parse_failed")

    if bool(content.get("archived")):
        # Still ingest so Core source_status / archived mirror stay truthful.
        pass

    try:
        ingest_payload = vacancy_detail_to_ingest(content)
    except NormalizeError as error:
        return fail(ux_status="error", code="page_parse_failed", extra={"error": str(error)})

    try:
        ingest = client.ingest_vacancy(ingest_payload)
    except CoreError as error:
        return fail(
            ux_status="error",
            code="core_ingest_failed",
            extra={"error": str(error)[:1000]},
        )

    outcome = str(ingest.get("outcome") or "")
    vacancy = ingest.get("vacancy") if isinstance(ingest.get("vacancy"), dict) else None
    if outcome not in {"created", "updated", "unchanged"} or not vacancy:
        return fail(
            ux_status="error", code="core_ingest_failed", extra={"error": "invalid_ingest_result"}
        )

    ux_status = "unchanged" if outcome == "unchanged" else "updated"
    if bool(content.get("archived")) or str(vacancy.get("source_status") or "") == "archived":
        ux_status = "unavailable"

    return with_recovery(
        {
            **base,
            "ok": True,
            "status": STATUS_AVAILABLE,
            "code": "ready",
            "ux_status": ux_status,
            "outcome": outcome,
            "vacancy": vacancy,
        }
    )
