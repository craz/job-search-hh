"""Read-only vacancy synchronization from HH into Core."""

from __future__ import annotations

from typing import Any

from job_search_hh.core_client import CoreError, CoreGateway
from job_search_hh.normalize import NormalizeError, idempotency_key, normalize_vacancy
from job_search_hh.providers import ProviderError, VacancyProvider


class SyncError(Exception):
    """Aggregate failure for sync orchestration boundaries."""


def sync_vacancies(
    provider: VacancyProvider,
    core: CoreGateway,
    *,
    text: str,
    per_page: int = 20,
) -> dict[str, Any]:
    """Fetch public vacancies, normalize them and write each once to Core."""
    try:
        items = provider.search(text=text, per_page=per_page)
    except ProviderError as error:
        raise SyncError(str(error)) from error

    created: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in items:
        try:
            payload = normalize_vacancy(item)
            vacancy = core.create_vacancy(payload, idempotency_key(str(payload["external_id"])))
            created.append(
                {
                    "external_id": payload["external_id"],
                    "core_id": vacancy.get("id"),
                    "title": payload["title"],
                }
            )
        except (NormalizeError, CoreError) as error:
            errors.append({"external_id": str(item.get("id") or ""), "error": str(error)})

    return {
        "text": text,
        "fetched": len(items),
        "synced": len(created),
        "items": created,
        "errors": errors,
        "external_writes_enabled": False,
    }
