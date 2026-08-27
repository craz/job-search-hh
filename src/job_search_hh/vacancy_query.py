"""Map SearchProfile criteria + execution policy to HH Web search URLs.

Only parameters verified against normal `hh.ru/search/vacancy` behaviour are
emitted. Unsupported inputs are reported explicitly (never silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

DEFAULT_SEARCH_BASE = "https://hh.ru/search/vacancy"

# Verified on live browser (2026-08-27): these query keys stick on the SERP URL.
SUPPORTED_CRITERIA_PARAMS = frozenset(
    {
        "text",
        "area",
        "salary",
        "experience",
        "employment",
        "schedule",
        "search_field",
        "only_with_salary",
    }
)
SUPPORTED_EXECUTION_PARAMS = frozenset({"order", "max_pages"})

# HH Web SERP uses a fixed page size (~50); API-style page_size is not a Web control.
WEB_PAGE_SIZE_UNSUPPORTED = (
    "HH Web search does not expose a compatible page_size control; "
    "observed SERP size is recorded after fetch"
)


@dataclass(frozen=True)
class SearchCriteria:
    """Semantic vacancy search intent (SearchProfile-shaped)."""

    text: str | None = None
    area: str | int | None = None
    salary: int | None = None
    experience: str | None = None
    employment: str | None = None
    schedule: str | None = None
    search_field: str | None = None
    only_with_salary: bool | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPolicy:
    """Run-time acquisition knobs (not SearchProfile)."""

    order: str | None = "publication_time"
    max_pages: int = 1
    page_size: int | None = None  # not mapped to Web; reported unsupported if set


@dataclass(frozen=True)
class QueryMapping:
    """Result of mapping criteria/execution onto a Web search URL."""

    url: str
    query: dict[str, str]
    unsupported: list[dict[str, str]]
    page_size_note: str | None


def _as_query_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def map_search_query(
    criteria: SearchCriteria,
    execution: ExecutionPolicy,
    *,
    page: int = 0,
    base_url: str = DEFAULT_SEARCH_BASE,
) -> QueryMapping:
    """Build one SERP URL and list unsupported inputs."""
    unsupported: list[dict[str, str]] = []
    query: dict[str, str] = {}

    def put(name: str, value: Any) -> None:
        rendered = _as_query_value(value)
        if rendered is None:
            return
        query[name] = rendered

    put("text", criteria.text)
    put("area", criteria.area)
    put("salary", criteria.salary)
    put("experience", criteria.experience)
    put("employment", criteria.employment)
    put("schedule", criteria.schedule)
    put("search_field", criteria.search_field)
    if criteria.only_with_salary is True:
        put("only_with_salary", True)
    elif criteria.only_with_salary is False:
        # Explicit false is valid on HH Web but usually redundant.
        put("only_with_salary", False)

    for key, value in criteria.extras.items():
        if key in SUPPORTED_CRITERIA_PARAMS:
            put(key, value)
        else:
            unsupported.append(
                {
                    "field": str(key),
                    "reason": "criterion_not_mapped_to_hh_web_search",
                }
            )

    page_size_note: str | None = None
    if execution.page_size is not None:
        unsupported.append(
            {
                "field": "page_size",
                "reason": "execution_page_size_not_supported_on_hh_web",
            }
        )
        page_size_note = WEB_PAGE_SIZE_UNSUPPORTED

    if execution.order:
        put("order_by", execution.order)
    else:
        unsupported.append(
            {
                "field": "order",
                "reason": "execution_order_empty",
            }
        )

    if page < 0:
        raise ValueError("page_must_be_non_negative")
    put("page", page)

    encoded = urlencode(query, doseq=True)
    url = f"{base_url.rstrip('/')}?{encoded}" if encoded else base_url.rstrip("/")
    return QueryMapping(
        url=url,
        query=query,
        unsupported=unsupported,
        page_size_note=page_size_note,
    )


def criteria_from_mapping(raw: dict[str, Any] | None) -> SearchCriteria:
    """Build SearchCriteria from a plain dict (CLI / tests)."""
    raw = raw or {}
    known = {
        "text",
        "area",
        "salary",
        "experience",
        "employment",
        "schedule",
        "search_field",
        "only_with_salary",
    }
    extras = {k: v for k, v in raw.items() if k not in known and v is not None}
    salary = raw.get("salary")
    salary_int: int | None = None if salary is None or salary == "" else int(salary)
    only = raw.get("only_with_salary")
    only_bool: bool | None
    if only is None:
        only_bool = None
    elif isinstance(only, bool):
        only_bool = only
    else:
        only_bool = str(only).strip().casefold() in {"1", "true", "yes", "on"}
    return SearchCriteria(
        text=str(raw["text"]) if raw.get("text") is not None else None,
        area=raw.get("area"),
        salary=salary_int,
        experience=str(raw["experience"]) if raw.get("experience") is not None else None,
        employment=str(raw["employment"]) if raw.get("employment") is not None else None,
        schedule=str(raw["schedule"]) if raw.get("schedule") is not None else None,
        search_field=str(raw["search_field"]) if raw.get("search_field") is not None else None,
        only_with_salary=only_bool,
        extras=extras,
    )
