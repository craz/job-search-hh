"""HH vacancy source-status check (R2.4.1b).

Opens a single vacancy detail page via browser RO transport and reports whether
the source currently looks active or archived. Auth/CAPTCHA/network/invalid
paths always yield ``status=unknown`` — never ``archived``.

Does **not** write to Core, does **not** delete anything, and does **not** pull
a SERP. Non-scope: Core lifecycle updates, batch revalidation, HH writes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from job_search_hh.egress import classify_browser_transport_error, egress_diagnostic
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

SourceStatus = Literal["active", "archived", "unknown"]

VacancyDetailReader = Callable[..., dict[str, Any]]

_ARCHIVE_EVIDENCE = "data-qa=vacancy-archived or body text matching archive markers"


@dataclass(frozen=True)
class VacancySourceStatusResult:
    """Observable source-status for one HH vacancy external id."""

    external_id: str
    status: SourceStatus
    checked_at: str  # ISO UTC
    evidence: str | None
    reason: str | None
    transport_status: str  # available / not_authorized / unavailable / action_required / etc.


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _novnc_url() -> str:
    return novnc_public_url()


def _envelope(
    result: VacancySourceStatusResult,
    *,
    code: str,
    action: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build API/CLI JSON: product status fields + recovery from transport_status."""
    payload: dict[str, Any] = {
        **asdict(result),
        "transport": TRANSPORT,
        "extractor_version": EXTRACTOR_VERSION,
        "code": code,
        "action": action or {"code": "none"},
        "hh_writes": False,
        "core_writes": False,
    }
    if extra:
        payload.update(extra)
    # ``with_recovery`` classifies from top-level status/code/action; product
    # ``status`` is active|archived|unknown, so feed transport_status instead.
    recovered = with_recovery({**payload, "status": result.transport_status})
    payload["recovery"] = recovered["recovery"]
    return payload


def check_vacancy_source_status(
    external_id: str,
    paths: SessionPaths | None = None,
    *,
    page_reader: VacancyDetailReader | None = None,
    timeout_seconds: float = 45.0,
    vacancy_url_template: str = DEFAULT_VACANCY_URL_TEMPLATE,
) -> dict[str, Any]:
    """Check whether one HH vacancy looks active or archived on the source.

    Returns a dict shaped as ``VacancySourceStatusResult`` plus recovery /
    safety envelope fields. Never writes to Core and never deletes.
    """
    resolved = paths or SessionPaths.from_env()
    checked_at = _utc_now()
    eid = (external_id or "").strip()

    def unknown(
        *,
        transport_status: str,
        code: str,
        reason: str | None = None,
        action: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _envelope(
            VacancySourceStatusResult(
                external_id=eid,
                status="unknown",
                checked_at=checked_at,
                evidence=None,
                reason=reason or code,
                transport_status=transport_status,
            ),
            code=code,
            action=action,
            extra=extra,
        )

    if not eid or not eid.isdigit():
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code="invalid_vacancy_id",
        )

    auth = auth_status(resolved)
    if not auth.get("login_ready"):
        return unknown(
            transport_status=STATUS_NOT_AUTHORIZED,
            code="browser_login_required",
            action={"code": "open_login", "novnc_url": _novnc_url()},
        )

    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code="profile_locked",
            action={"code": "confirm_login", "novnc_url": _novnc_url()},
        )

    vacancy_url = vacancy_url_template.format(external_id=eid)
    reader = page_reader or _read_single_vacancy_detail
    try:
        lock.acquire("vacancy-source-status")
        try:
            raw = reader(
                profile_dir=resolved.profile_dir,
                vacancy_url=vacancy_url,
                timeout_ms=int(timeout_seconds * 1000),
            )
        finally:
            lock.release()
    except SessionError as error:
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code=str(error) or "transport_unavailable",
        )
    except Exception as error:
        code = classify_browser_transport_error(error) or "browser_vacancy_read_failed"
        extra = {"egress": egress_diagnostic()} if code == "browser_proxy_unavailable" else None
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code=code,
            extra=extra,
        )

    if not isinstance(raw, dict):
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code="invalid_vacancy_page",
        )

    kind = str(raw.get("kind") or "")
    if kind == "login_required":
        return unknown(
            transport_status=STATUS_NOT_AUTHORIZED,
            code="browser_session_not_logged_in",
            action={"code": "open_login", "novnc_url": _novnc_url()},
        )
    if kind == "captcha_or_action_required":
        return unknown(
            transport_status=STATUS_ACTION_REQUIRED,
            code="browser_captcha_or_action_required",
            action={"code": "confirm_login", "novnc_url": _novnc_url()},
        )
    if kind == "permission_blocked":
        return unknown(
            transport_status=STATUS_PERMISSION_BLOCKED,
            code="browser_vacancy_forbidden",
        )
    if kind != "ok":
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code="page_parse_failed" if kind == "invalid" else "vacancy_detail_failed",
        )

    content_obj = raw.get("content")
    content: dict[str, Any] = content_obj if isinstance(content_obj, dict) else {}
    if not content.get("external_id") or not content.get("title"):
        return unknown(
            transport_status=STATUS_UNAVAILABLE,
            code="page_parse_failed",
        )

    archived = bool(content.get("archived"))
    if archived:
        result = VacancySourceStatusResult(
            external_id=eid,
            status="archived",
            checked_at=checked_at,
            evidence=_ARCHIVE_EVIDENCE,
            reason=None,
            transport_status=STATUS_AVAILABLE,
        )
        return _envelope(result, code="ready")

    result = VacancySourceStatusResult(
        external_id=eid,
        status="active",
        checked_at=checked_at,
        evidence=None,
        reason=None,
        transport_status=STATUS_AVAILABLE,
    )
    return _envelope(result, code="ready")
