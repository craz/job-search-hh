"""Normalize public HH vacancy payloads into Core VacancyCreate fields."""

from __future__ import annotations

from typing import Any

SOURCE = "hh"


class NormalizeError(Exception):
    """Reject incomplete HH items before any Core write."""


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def description_from_item(item: dict[str, Any]) -> str | None:
    """Prefer full description; fall back to public search snippets."""
    direct = _text(item.get("description"))
    if direct:
        return direct
    snippet = item.get("snippet")
    if isinstance(snippet, dict):
        parts = [_text(snippet.get("requirement")), _text(snippet.get("responsibility"))]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    return None


def normalize_vacancy(item: dict[str, Any]) -> dict[str, Any]:
    """Map one HH vacancy document to Core's public create contract."""
    vacancy_id = _text(item.get("id"))
    title = _text(item.get("name") or item.get("title"))
    url = _text(item.get("alternate_url") or item.get("url"))
    raw_employer = item.get("employer")
    employer: dict[str, Any] = raw_employer if isinstance(raw_employer, dict) else {}
    company_name = _text(employer.get("name") or item.get("company_name"))
    company_external_id = _text(employer.get("id") or item.get("company_external_id"))
    if not vacancy_id or not title or not url or not company_name:
        raise NormalizeError("incomplete_vacancy")
    if not company_external_id:
        company_external_id = f"name:{company_name.casefold()}"
    payload: dict[str, Any] = {
        "company_name": company_name,
        "company_external_id": company_external_id,
        "source": SOURCE,
        "external_id": vacancy_id,
        "title": title,
        "url": url,
    }
    description = description_from_item(item)
    if description:
        payload["description"] = description
    return payload


def idempotency_key(external_id: str) -> str:
    """Stable replay key for one HH vacancy identity."""
    return f"hh:vacancy:{external_id}"


def application_idempotency_key(external_id: str) -> str:
    """Stable replay key for one HH application/negotiation identity."""
    return f"hh:application:{external_id}"


_RESULT_MAP = {
    "response": "reply",
    "reply": "reply",
    "interview": "interview",
    "discard": "rejected",
    "rejected": "rejected",
    "offer": "offer",
}


def normalize_application(item: dict[str, Any], *, vacancy_id: str) -> dict[str, Any]:
    """Map one HH negotiation/application fact to Core ApplicationCreate."""
    external_id = _text(item.get("id") or item.get("external_id"))
    if not external_id or not vacancy_id.strip():
        raise NormalizeError("incomplete_application")
    payload: dict[str, Any] = {
        "vacancy_id": vacancy_id,
        "source": SOURCE,
        "external_id": external_id,
    }
    applied_at = _text(item.get("created_at") or item.get("applied_at"))
    if applied_at:
        payload["applied_at"] = applied_at
    state = _text(item.get("state") or item.get("result")).casefold()
    if state in _RESULT_MAP:
        payload["result"] = _RESULT_MAP[state]
    return payload


def vacancy_external_id_from_application(item: dict[str, Any]) -> str:
    """Extract the HH vacancy identity referenced by a negotiation payload."""
    vacancy = item.get("vacancy")
    if isinstance(vacancy, dict):
        return _text(vacancy.get("id") or vacancy.get("external_id"))
    return _text(item.get("vacancy_id") or item.get("vacancy_external_id"))
