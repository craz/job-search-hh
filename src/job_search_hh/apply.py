"""Dry-run and gated limited apply without accidental HH submits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_search_hh.apply_transport import ApplyTransport, ApplyTransportError, FakeApplyTransport


class ApplyError(Exception):
    """Stable failure for incomplete plans or unsafe apply execution."""


def load_apply_plan(path: Path) -> list[dict[str, Any]]:
    """Load a synthetic apply plan list from disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise ApplyError("invalid_apply_plan")
    return [item for item in items if isinstance(item, dict)]


def _normalize_intent(item: dict[str, Any], *, live: bool) -> dict[str, Any]:
    vacancy_id = str(item.get("vacancy_id") or item.get("vacancy_external_id") or "").strip()
    resume_id = str(item.get("resume_id") or "").strip()
    message = str(item.get("message") or item.get("cover_letter") or "")
    if not vacancy_id or not resume_id:
        raise ApplyError("incomplete_apply_plan_item")
    body = {
        "vacancy_id": vacancy_id,
        "resume_id": resume_id,
        "message": message,
    }
    return {
        "vacancy_external_id": vacancy_id,
        "resume_id": resume_id,
        "message": message,
        "path": "/negotiations",
        "body": body,
        "live": live,
    }


def dry_run_apply(
    plan: list[dict[str, Any]],
    transport: ApplyTransport | None = None,
) -> dict[str, Any]:
    """Plan HH applications through a fake transport and return an audit report."""
    client = transport or FakeApplyTransport()
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    audit: list[dict[str, Any]] = []
    write_attempted = False

    for raw in plan:
        try:
            intent = _normalize_intent(raw, live=False)
            result = client.submit(intent)
            would_send = result.get("would_send")
            if not isinstance(would_send, dict):
                raise ApplyError("invalid_transport_result")
            items.append(
                {
                    "vacancy_external_id": intent["vacancy_external_id"],
                    "would_send": would_send,
                }
            )
            audit.append(would_send)
        except (ApplyError, ApplyTransportError) as error:
            write_attempted = write_attempted or isinstance(error, ApplyTransportError)
            errors.append(
                {
                    "vacancy_external_id": str(
                        raw.get("vacancy_id") or raw.get("vacancy_external_id") or ""
                    ),
                    "error": str(error),
                }
            )

    if isinstance(client, FakeApplyTransport):
        write_attempted = write_attempted or client.write_attempted
        audit = list(client.audit)

    return {
        "mode": "dry-run",
        "planned": len(plan),
        "simulated": len(items),
        "items": items,
        "audit": audit,
        "errors": errors,
        "external_writes_enabled": False,
        "hh_write_attempted": write_attempted,
        "core_application_created": False,
    }


def limited_apply(
    plan: list[dict[str, Any]],
    *,
    external_writes_enabled: bool,
    authorized: bool,
    limit: int = 1,
) -> dict[str, Any]:
    """Gate limited apply; never open HH write HTTP in this scaffold."""
    limit = max(1, limit)
    base: dict[str, Any] = {
        "mode": "limited",
        "planned": len(plan),
        "limit": limit,
        "captcha_stop": True,
        "items": [],
        "errors": [],
        "external_writes_enabled": external_writes_enabled,
        "authorized": authorized,
        "hh_write_attempted": False,
        "core_application_created": False,
        "execution": "refused",
    }
    if not external_writes_enabled:
        return {
            **base,
            "errors": [{"error": "external_writes_disabled"}],
        }
    if not authorized:
        return {
            **base,
            "errors": [{"error": "authorization_required"}],
        }

    selected = plan[:limit]
    items = [
        {
            "vacancy_external_id": str(
                item.get("vacancy_id") or item.get("vacancy_external_id") or ""
            ),
            "status": "gated_ready",
            "would_send": {
                "method": "POST",
                "path": "/negotiations",
                "body_keys": ["message", "resume_id", "vacancy_id"],
            },
        }
        for item in selected
        if isinstance(item, dict)
    ]
    return {
        **base,
        "selected": len(items),
        "items": items,
        "execution": "not_implemented",
        "errors": [],
    }
