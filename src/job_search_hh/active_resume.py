"""Local active HH resume selection (R1.4).

Source of truth for R1.4 is HH state JSON (not Core CandidateProfile — that is R1.5).
Browser resume list remains the source of *available* resumes; this module only
persists the operator's explicit selection (one id or none) across reload/restart.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from job_search_hh.session import SessionPaths

SELECTION_NONE = "none"
SELECTION_ACTIVE = "active"
SELECTION_STALE = "stale"
SELECTION_UNAVAILABLE = "unavailable"

ACTIVE_RESUME_FILENAME = "active_resume.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def active_resume_path(paths: SessionPaths) -> Path:
    return paths.state_dir / ACTIVE_RESUME_FILENAME


def read_stored_external_id(paths: SessionPaths) -> str | None:
    """Return persisted external_id or None when cleared / missing / corrupt."""
    path = active_resume_path(paths)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    external_id = payload.get("external_id")
    if external_id is None:
        return None
    if not isinstance(external_id, str):
        return None
    external_id = external_id.strip()
    return external_id or None


def write_stored_external_id(paths: SessionPaths, external_id: str | None) -> None:
    """Persist selection (id or explicit none). Survives process/container restart."""
    paths.ensure()
    path = active_resume_path(paths)
    payload = {
        "external_id": external_id,
        "selected_at": _utc_now() if external_id else None,
        "schema_version": 1,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def clear_stored_selection(paths: SessionPaths) -> None:
    write_stored_external_id(paths, None)


def attach_selection(report: dict[str, Any], paths: SessionPaths) -> dict[str, Any]:
    """Annotate a resumes list report with active markers and selection status.

    When the list is not ``available``, selection UI is not operable: stored id
    may still be returned for diagnostics, but ``active_resume`` stays null and
    items are not marked active (auth failure ≠ «active resume missing»).
    """
    stored = read_stored_external_id(paths)
    items = report.get("items")
    if not isinstance(items, list):
        items = []
        report["items"] = items

    list_available = str(report.get("status") or "") == "available"
    annotated: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["active"] = False
        annotated.append(item)
    report["items"] = annotated

    if not list_available:
        report["selection"] = {
            "status": SELECTION_UNAVAILABLE,
            "external_id": stored,
            "available": False,
        }
        report["active_resume"] = None
        return report

    if stored is None:
        report["selection"] = {
            "status": SELECTION_NONE,
            "external_id": None,
            "available": True,
        }
        report["active_resume"] = None
        return report

    match = next((item for item in annotated if item.get("external_id") == stored), None)
    if match is None:
        report["selection"] = {
            "status": SELECTION_STALE,
            "external_id": stored,
            "available": True,
            "action": {"code": "reselect"},
        }
        report["active_resume"] = None
        return report

    match["active"] = True
    report["selection"] = {
        "status": SELECTION_ACTIVE,
        "external_id": stored,
        "available": True,
    }
    report["active_resume"] = {
        "external_id": match["external_id"],
        "title": match["title"],
    }
    return report


def set_active_resume(
    paths: SessionPaths,
    external_id: str | None,
    *,
    list_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Set or clear active resume; reject ids not in an available list.

    ``list_report`` must be a fresh ``list_resumes`` payload (caller supplies it
    so browser scrape is not duplicated). Returns annotated resumes payload on
    success, or an error envelope with ``ok=False``.
    """
    if external_id is not None:
        if not isinstance(external_id, str) or not external_id.strip():
            return {
                "ok": False,
                "code": "invalid_resume_id",
                "message": "external_id must be a non-empty string or null",
                "resumes": attach_selection(
                    dict(list_report or {"status": "unavailable", "items": []}), paths
                ),
            }
        external_id = external_id.strip()

    if list_report is None:
        list_report = {"status": "unavailable", "items": [], "code": "list_required"}

    report = dict(list_report)
    raw_items = report.get("items")
    if isinstance(raw_items, list):
        report["items"] = [dict(item) if isinstance(item, dict) else item for item in raw_items]

    if external_id is None:
        clear_stored_selection(paths)
        return {"ok": True, "code": "cleared", "resumes": attach_selection(report, paths)}

    if str(report.get("status") or "") != "available":
        return {
            "ok": False,
            "code": "selection_unavailable",
            "message": "Resume list is not available; cannot change active selection",
            "resumes": attach_selection(report, paths),
        }

    known = {
        str(item.get("external_id"))
        for item in (report.get("items") or [])
        if isinstance(item, dict) and item.get("external_id")
    }
    if external_id not in known:
        return {
            "ok": False,
            "code": "invalid_resume_id",
            "message": "external_id is not in the current resume list",
            "resumes": attach_selection(report, paths),
        }

    write_stored_external_id(paths, external_id)
    return {"ok": True, "code": "selected", "resumes": attach_selection(report, paths)}
