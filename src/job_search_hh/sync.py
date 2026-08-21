"""Read-only vacancy and application synchronization from HH into Core."""

from __future__ import annotations

from typing import Any

from job_search_hh.core_client import CoreError, CoreGateway
from job_search_hh.normalize import (
    SOURCE,
    NormalizeError,
    application_idempotency_key,
    idempotency_key,
    metric_idempotency_key,
    normalize_application,
    normalize_metric,
    normalize_vacancy,
    vacancy_external_id_from_application,
)
from job_search_hh.providers import (
    ApplicationProvider,
    MetricProvider,
    ProviderError,
    VacancyProvider,
)


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


def _resolve_vacancy_id(core: CoreGateway, item: dict[str, Any]) -> str:
    vacancy_external_id = vacancy_external_id_from_application(item)
    if not vacancy_external_id:
        raise NormalizeError("missing_vacancy_reference")

    for vacancy in core.list_vacancies():
        if (
            vacancy.get("source") == SOURCE
            and str(vacancy.get("external_id")) == vacancy_external_id
        ):
            return str(vacancy["id"])

    embedded = item.get("vacancy")
    if isinstance(embedded, dict) and (embedded.get("name") or embedded.get("title")):
        payload = normalize_vacancy(embedded)
        created = core.create_vacancy(payload, idempotency_key(str(payload["external_id"])))
        return str(created["id"])

    raise CoreError(f"vacancy_not_found:{vacancy_external_id}")


def sync_applications(provider: ApplicationProvider, core: CoreGateway) -> dict[str, Any]:
    """Import existing HH applications into Core without submitting new ones."""
    try:
        items = provider.list_applications()
    except ProviderError as error:
        raise SyncError(str(error)) from error

    created: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in items:
        try:
            vacancy_id = _resolve_vacancy_id(core, item)
            payload = normalize_application(item, vacancy_id=vacancy_id)
            application = core.create_application(
                payload, application_idempotency_key(str(payload["external_id"]))
            )
            created.append(
                {
                    "external_id": payload["external_id"],
                    "core_id": application.get("id"),
                    "vacancy_id": vacancy_id,
                }
            )
        except (NormalizeError, CoreError) as error:
            errors.append({"external_id": str(item.get("id") or ""), "error": str(error)})

    return {
        "fetched": len(items),
        "synced": len(created),
        "items": created,
        "errors": errors,
        "external_writes_enabled": False,
        "hh_write_attempted": False,
    }


def sync_metrics(provider: MetricProvider, core: CoreGateway) -> dict[str, Any]:
    """Import daily metric snapshots into Core without HH side effects."""
    try:
        items = provider.list_metrics()
    except ProviderError as error:
        raise SyncError(str(error)) from error

    created: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in items:
        try:
            metric_date, payload = normalize_metric(item)
            metric = core.upsert_metric(
                metric_date, payload, metric_idempotency_key(metric_date, payload)
            )
            created.append(
                {
                    "metric_date": metric_date,
                    "applications": metric.get("applications", payload.get("applications")),
                    "views_total": metric.get("views_total", payload.get("views_total")),
                }
            )
        except (NormalizeError, CoreError) as error:
            errors.append(
                {
                    "metric_date": str(item.get("metric_date") or item.get("date") or ""),
                    "error": str(error),
                }
            )

    return {
        "fetched": len(items),
        "synced": len(created),
        "items": created,
        "errors": errors,
        "external_writes_enabled": False,
        "hh_write_attempted": False,
    }
