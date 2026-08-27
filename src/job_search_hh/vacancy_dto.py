"""Provider-level HH vacancy source DTOs (independent of Core Vacancy)."""

from __future__ import annotations

from typing import Any, TypedDict


class HhVacancySummary(TypedDict, total=False):
    """List-first SERP summary. Absent keys mean source did not expose them."""

    external_id: str
    title: str
    url: str
    employer_id: str
    employer_name: str
    salary_text: str
    area_text: str
    experience_text: str
    work_format_text: str
    published_text: str
    source_page: int
    source_url: str


class HhVacancyDetail(TypedDict, total=False):
    """Detail-page source content for later scoring-ready normalization."""

    external_id: str
    title: str
    url: str
    employer_id: str
    employer_name: str
    description: str
    salary_text: str
    area_text: str
    employment_text: str
    schedule_text: str
    work_format_text: str
    experience_text: str
    published_text: str
    archived: bool


SUMMARY_ALLOWLIST = frozenset(HhVacancySummary.__annotations__)
DETAIL_ALLOWLIST = frozenset(HhVacancyDetail.__annotations__)


def allowlist_summary(raw: dict[str, Any]) -> HhVacancySummary:
    """Keep only declared summary fields with non-empty values."""
    out: HhVacancySummary = {}
    for key in SUMMARY_ALLOWLIST:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key == "source_page" and isinstance(value, int):
            out["source_page"] = value
        elif key == "archived" and isinstance(value, bool):
            continue
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()  # type: ignore[literal-required]
        elif isinstance(value, (int, bool)):
            continue
    return out


def allowlist_detail(raw: dict[str, Any]) -> HhVacancyDetail:
    """Keep only declared detail fields with non-empty values."""
    out: HhVacancyDetail = {}
    for key in DETAIL_ALLOWLIST:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key == "archived" and isinstance(value, bool):
            out["archived"] = value
        elif isinstance(value, str) and value.strip():
            out[key] = value.strip()  # type: ignore[literal-required]
    return out
