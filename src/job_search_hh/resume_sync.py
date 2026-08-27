"""Manual HH → Core resume content sync (R2.1.3 / TECH-US-01.4).

Uses the R2.1.2 browser RO extractor, then POSTs allowlisted content to Core
``POST /api/v1/resume-versions``. Never invents a ResumeVersion on extract
failure. Does not auto-sync on select.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from job_search_hh.active_resume import read_stored_external_id
from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient, CoreError
from job_search_hh.recovery import with_recovery
from job_search_hh.resume_content import ResumeDetailReader, read_resume_content
from job_search_hh.session import SessionPaths

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_PERMISSION_BLOCKED = "permission_blocked"
STATUS_ACTION_REQUIRED = "action_required"

ContentReader = Callable[..., dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sync_resume_content(
    *,
    external_resume_id: str | None = None,
    paths: SessionPaths | None = None,
    content_reader: ContentReader | None = None,
    core: CoreClient | None = None,
    page_reader: ResumeDetailReader | None = None,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Extract active (or explicit) HH resume content and ingest into Core.

    On extract/recovery failure: returns failure envelope and does **not** call
    Core. On Core failure after a successful extract: reports Core error without
    inventing a local ResumeVersion.
    """
    return with_recovery(
        _sync_resume_content_raw(
            external_resume_id=external_resume_id,
            paths=paths,
            content_reader=content_reader,
            core=core,
            page_reader=page_reader,
            timeout_seconds=timeout_seconds,
        )
    )


def _sync_resume_content_raw(
    *,
    external_resume_id: str | None,
    paths: SessionPaths | None,
    content_reader: ContentReader | None,
    core: CoreClient | None,
    page_reader: ResumeDetailReader | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    resolved = paths or SessionPaths.from_env()
    checked_at = _utc_now()
    target_id = (external_resume_id or "").strip() or read_stored_external_id(resolved)

    base: dict[str, Any] = {
        "operation": "manual_resume_sync",
        "external_resume_id": target_id,
        "source": "hh",
        "checked_at": checked_at,
        "extract": None,
        "ingest": None,
        "candidate_context": None,
        "action": {"code": "none"},
    }

    if not target_id:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "no_active_resume",
            "ok": False,
            "action": {"code": "select_resume"},
        }

    reader = content_reader or read_resume_content
    if content_reader is None:
        extract = reader(
            target_id,
            resolved,
            page_reader=page_reader,
            timeout_seconds=timeout_seconds,
        )
    else:
        extract = reader(target_id)

    if not isinstance(extract, dict):
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "extract_invalid",
            "ok": False,
            "extract": {"status": STATUS_UNAVAILABLE, "code": "extract_invalid"},
        }

    extract_status = str(extract.get("status") or "")
    base["extract"] = {
        "status": extract_status,
        "code": extract.get("code"),
        "extractor_version": extract.get("extractor_version"),
        "captured_at": extract.get("captured_at"),
        "recovery": extract.get("recovery"),
        "action": extract.get("action"),
    }
    if extract.get("action"):
        base["action"] = extract["action"]

    if extract_status != STATUS_AVAILABLE:
        # Propagate extract status; never invent Core ResumeVersion.
        return {
            **base,
            "status": extract_status or STATUS_UNAVAILABLE,
            "code": extract.get("code") or "extract_failed",
            "ok": False,
            "recovery": extract.get("recovery"),
        }

    content = extract.get("content")
    if not isinstance(content, dict) or not content:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "resume_content_empty",
            "ok": False,
        }

    client = core or CoreClient(Settings.from_env().core_url)
    payload = {
        "source": "hh",
        "external_resume_id": target_id,
        "transport": str(extract.get("transport") or "browser_readonly"),
        "extractor_version": extract.get("extractor_version"),
        "captured_at": extract.get("captured_at"),
        "content": content,
    }
    try:
        ingest = client.create_resume_version(payload)
    except CoreError as error:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "core_ingest_failed",
            "ok": False,
            "ingest": {"ok": False, "message": str(error)[:300]},
        }

    created = bool(ingest.get("created"))
    resume_version = ingest.get("resume_version") if isinstance(ingest, dict) else None
    raw_context = ingest.get("candidate_context") if isinstance(ingest, dict) else None
    candidate_context = raw_context if isinstance(raw_context, dict) else None
    version_id = None
    content_hash = None
    if isinstance(resume_version, dict):
        version_id = resume_version.get("id")
        content_hash = resume_version.get("content_hash")

    return {
        **base,
        "status": STATUS_AVAILABLE,
        "code": "synced" if created else "unchanged",
        "ok": True,
        "ingest": {
            "ok": True,
            "created": created,
            "resume_version_id": version_id,
            "content_hash": content_hash,
        },
        "candidate_context": candidate_context,
    }
