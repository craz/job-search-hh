"""HH resume-suitable vacancy discovery (R2.2.5 primary acquisition).

Builds the normal HH Web SERP for «подходящие вакансии для резюме» and validates
that the fetched page still matches the expected active resume.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from job_search_hh.vacancy_query import QueryMapping

DEFAULT_SEARCH_BASE = "https://hh.ru/search/vacancy"
RESUME_SUITABLE_FROM = "resumelist"
RESUME_SUITABLE_LABEL = "vacancies_for_resume_button"
RESUME_SUITABLE_HHTM_FROM = "resume_list"

_SUITABLE_HEADING_RE = re.compile(
    r"Найдено\s+([\d\s\u00a0]+)\s+подходящ",
    re.IGNORECASE,
)
_DIGITS_RE = re.compile(r"\D+")


def map_resume_suitable_query(
    resume_external_id: str,
    *,
    page: int = 0,
    order: str = "publication_time",
    base_url: str = DEFAULT_SEARCH_BASE,
) -> QueryMapping:
    """Build resume-specific suitable-vacancies SERP URL (normal HH Web)."""
    resume_id = str(resume_external_id or "").strip()
    if not resume_id:
        raise ValueError("resume_external_id_required")
    if page < 0:
        raise ValueError("page_must_be_non_negative")
    query = {
        "resume": resume_id,
        "from": RESUME_SUITABLE_FROM,
        "hhtmFromLabel": RESUME_SUITABLE_LABEL,
        "hhtmFrom": RESUME_SUITABLE_HHTM_FROM,
        "order_by": str(order or "publication_time").strip() or "publication_time",
        "page": str(page),
    }
    encoded = urlencode(query)
    return QueryMapping(
        url=f"{base_url.rstrip('/')}?{encoded}",
        query={k: str(v) for k, v in query.items()},
        unsupported=[],
        page_size_note=None,
    )


def parse_source_total(found_text: str | None) -> int | None:
    """Extract HH total suitable count from SERP heading text when present."""
    if not found_text:
        return None
    match = _SUITABLE_HEADING_RE.search(found_text)
    if not match:
        # Fallback: any leading number in found_text.
        digits = _DIGITS_RE.sub("", found_text)
        return int(digits) if digits else None
    digits = _DIGITS_RE.sub("", match.group(1))
    return int(digits) if digits else None


def validate_resume_suitable_page(
    *,
    expected_resume_id: str,
    final_url: str,
    found_text: str | None,
    card_count: int,
) -> dict[str, Any]:
    """Guard: SERP must still be suitable-for-resume for the expected active id.

    Returns ``{"ok": True, "source_total": int|None}`` or
    ``{"ok": False, "code": "...", "detail": "..."}``.
    """
    expected = str(expected_resume_id or "").strip()
    parsed = urlparse(final_url or "")
    query = parse_qs(parsed.query)
    resume_values = query.get("resume") or []
    actual = str(resume_values[0]).strip() if resume_values else ""
    if not actual or actual != expected:
        return {
            "ok": False,
            "code": "resume_search_page_mismatch",
            "detail": "effective_url_resume_mismatch",
        }
    label_values = query.get("hhtmFromLabel") or []
    label = str(label_values[0]).strip() if label_values else None
    if label and label != RESUME_SUITABLE_LABEL:
        return {
            "ok": False,
            "code": "resume_search_page_mismatch",
            "detail": "hhtmFromLabel_mismatch",
        }
    text = (found_text or "").strip()
    if not text or "подходящ" not in text.lower() or "резюм" not in text.lower():
        return {
            "ok": False,
            "code": "resume_search_page_mismatch",
            "detail": "suitable_heading_missing",
        }
    if card_count < 0:
        return {
            "ok": False,
            "code": "resume_search_page_mismatch",
            "detail": "invalid_result_structure",
        }
    return {"ok": True, "source_total": parse_source_total(text)}


def rewrite_url_keep_host(template_url: str, final_host_url: str) -> str:
    """Keep regional host from a redirect while preserving query from template."""
    final = urlparse(final_host_url)
    templ = urlparse(template_url)
    if not final.netloc:
        return template_url
    return urlunparse((final.scheme or templ.scheme, final.netloc, templ.path, "", templ.query, ""))
