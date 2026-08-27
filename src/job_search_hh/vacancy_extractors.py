"""Allowlist-oriented Playwright extractors for HH vacancy SERP and detail pages.

Selectors live here only — keep DOM fragility localized.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from job_search_hh.vacancy_dto import (
    HhVacancyDetail,
    HhVacancySummary,
    allowlist_detail,
    allowlist_summary,
)

EXTRACTOR_VERSION = "hh-browser-vacancy-ro-v1"

_VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")

SEARCH_EXTRACT_JS = """() => {
  const text = (el) =>
    el ? (el.textContent || '').trim().replace(/\\s+/g, ' ') : '';
  const qa = (sel) => document.querySelector(sel);

  if (qa(
    '[data-qa="account-login-form"], ' +
    '[data-qa="applicant-login-card"], [data-qa="login"]'
  )) {
    return { kind: 'login_required', items: [], meta: {} };
  }
  if (qa(
    '[data-qa="account-captcha"], [data-qa="captcha"], ' +
    '.bloko-captcha, iframe[src*="captcha"]'
  )) {
    return { kind: 'captcha_or_action_required', items: [], meta: {} };
  }
  if (qa('[data-qa="error-forbidden"], [data-qa="vacancy-forbidden"]')) {
    return { kind: 'permission_blocked', items: [], meta: {} };
  }

  const foundNode =
    qa('[data-qa="vacancies-total-found"]') ||
    qa('h1[data-qa="bloko-header-3"]') ||
    qa('h1');
  const found_text = text(foundNode);

  const pager = Array.from(document.querySelectorAll('[data-qa="pager-page"]'))
    .map((n) => text(n))
    .filter(Boolean);
  const items = [];
  const seen = new Set();
  const cards = Array.from(
    document.querySelectorAll('[data-qa="vacancy-serp__vacancy"]')
  );

  for (const card of cards) {
    const link =
      card.querySelector('a[data-qa="serp-item__title"]') ||
      card.querySelector('a[href*="/vacancy/"]');
    if (!link) continue;
    const href = link.getAttribute('href') || '';
    const match = href.match(/\\/vacancy\\/(\\d+)/);
    if (!match) continue;
    const id = match[1];
    if (seen.has(id)) continue;
    seen.add(id);

    const title =
      text(card.querySelector('[data-qa="serp-item__title-text"]')) ||
      text(link);
    if (!title || title.length < 2) continue;

    const employerNode =
      card.querySelector('[data-qa="vacancy-serp__vacancy-employer-text"]') ||
      card.querySelector('[data-qa="vacancy-serp__vacancy-employer"]');
    const employer_name = text(employerNode);
    let employer_id = '';
    const employerLink =
      card.querySelector('a[href*="/employer/"]') ||
      (employerNode && employerNode.closest('a[href*="/employer/"]'));
    if (employerLink) {
      const em = (employerLink.getAttribute('href') || '').match(
        /\\/employer\\/(\\d+)/
      );
      if (em) employer_id = em[1];
    }

    const salary = text(
      card.querySelector('[data-qa="vacancy-serp__vacancy-compensation"]') ||
      card.querySelector('[data-qa*="compensation"]')
    );
    const area = text(
      card.querySelector('[data-qa="vacancy-serp__vacancy-address"]')
    );
    const experienceNode = card.querySelector(
      '[data-qa^="vacancy-serp__vacancy-work-experience-"]'
    );
    const experience_text = experienceNode
      ? (experienceNode.getAttribute('data-qa') || '')
          .replace('vacancy-serp__vacancy-work-experience-', '')
      : '';
    const formatNode = card.querySelector(
      '[data-qa^="vacancy-label-work-schedule-"]'
    );
    const work_format_text = formatNode
      ? (formatNode.getAttribute('data-qa') || '')
          .replace('vacancy-label-work-schedule-', '')
      : '';
    const published = text(
      card.querySelector('[data-qa="vacancy-serp-item-activity"]')
    );

    items.push({
      external_id: id,
      title,
      url: href,
      employer_id,
      employer_name,
      salary_text: salary,
      area_text: area,
      experience_text,
      work_format_text,
      published_text: published,
    });
  }

  return {
    kind: items.length ? 'ok' : 'empty',
    items,
    meta: {
      found_text,
      pager_labels: pager,
      observed_page_size: items.length,
    },
  };
}"""

DETAIL_EXTRACT_JS = """() => {
  const text = (el) =>
    el ? (el.textContent || '').trim().replace(/\\s+/g, ' ') : '';
  const qa = (sel) => document.querySelector(sel);

  if (qa(
    '[data-qa="account-login-form"], ' +
    '[data-qa="applicant-login-card"], [data-qa="login"]'
  )) {
    return { kind: 'login_required', content: {} };
  }
  if (qa(
    '[data-qa="account-captcha"], [data-qa="captcha"], ' +
    '.bloko-captcha, iframe[src*="captcha"]'
  )) {
    return { kind: 'captcha_or_action_required', content: {} };
  }
  if (qa('[data-qa="error-forbidden"], [data-qa="vacancy-forbidden"]')) {
    return { kind: 'permission_blocked', content: {} };
  }

  const href = location.href || '';
  const idMatch = href.match(/\\/vacancy\\/(\\d+)/);
  const external_id = idMatch ? idMatch[1] : '';
  const title = text(qa('[data-qa="vacancy-title"], h1'));
  const employer_name = text(
    qa('[data-qa="vacancy-company-name"]') ||
    qa('[data-qa="vacancy-company__details"]')
  );
  let employer_id = '';
  const employerLink = qa('a[data-qa="vacancy-company-name"], a[href*="/employer/"]');
  if (employerLink) {
    const em = (employerLink.getAttribute('href') || '').match(/\\/employer\\/(\\d+)/);
    if (em) employer_id = em[1];
  }

  const description = text(qa('[data-qa="vacancy-description"]'));
  const salary_text = text(
    qa('[data-qa="vacancy-salary"]') ||
    qa('[data-qa="vacancy-salary-compensation"]') ||
    qa('[data-qa*="vacancy-salary"]')
  );
  const area_text = text(
    qa('[data-qa="vacancy-view-raw-address"]') ||
    qa('[data-qa="vacancy-address-with-map"]')
  );
  const experience_text = text(qa('[data-qa="vacancy-experience"]'));
  const employment_text = text(qa('[data-qa="common-employment-text"]'));
  const schedule_text = text(qa('[data-qa="work-schedule-by-days-text"]'));
  const work_format_text = text(qa('[data-qa="work-formats-text"]'));
  const published_text = text(
    qa('[data-qa="vacancy-view-vacancy-creation-date"]') ||
    qa('[data-qa*="creation-date"]')
  );
  const archived =
    !!qa('[data-qa="vacancy-archived"]') ||
    /вакансия.*архив|в архиве/i.test(
      (document.body && document.body.innerText || '').slice(0, 2500)
    );

  if (!external_id || !title) {
    return { kind: 'invalid', content: {} };
  }

  return {
    kind: 'ok',
    content: {
      external_id,
      title,
      url: href.split('?')[0],
      employer_id,
      employer_name,
      description,
      salary_text,
      area_text,
      employment_text,
      schedule_text,
      work_format_text,
      experience_text,
      published_text,
      archived,
    },
  };
}"""


def canonicalize_vacancy_url(href: str, *, base: str = "https://hh.ru") -> str:
    """Normalize regional / relative vacancy links to a stable https URL."""
    raw = (href or "").strip()
    if not raw:
        return ""
    absolute = urljoin(base.rstrip("/") + "/", raw)
    parsed = urlparse(absolute)
    match = _VACANCY_ID_RE.search(parsed.path)
    if not match:
        return absolute.split("?")[0]
    return f"https://hh.ru/vacancy/{match.group(1)}"


def normalize_search_payload(
    payload: dict[str, Any],
    *,
    page: int,
    source_url: str,
) -> dict[str, Any]:
    """Normalize extractor output into allowlisted summaries + meta."""
    kind = str(payload.get("kind") or "invalid")
    raw_items_obj = payload.get("items")
    raw_items: list[Any] = raw_items_obj if isinstance(raw_items_obj, list) else []
    items: list[HhVacancySummary] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        external_id = str(raw.get("external_id") or "").strip()
        if not external_id or external_id in seen:
            continue
        seen.add(external_id)
        url = canonicalize_vacancy_url(str(raw.get("url") or ""))
        if not url:
            url = f"https://hh.ru/vacancy/{external_id}"
        merged: dict[str, Any] = dict(raw)
        merged.update(
            {
                "external_id": external_id,
                "url": url,
                "source_page": page,
                "source_url": source_url,
            }
        )
        summary = allowlist_summary(merged)
        if summary.get("external_id") and summary.get("title"):
            items.append(summary)
    meta_obj = payload.get("meta")
    meta: dict[str, Any] = meta_obj if isinstance(meta_obj, dict) else {}
    pager_obj = meta.get("pager_labels")
    pager_labels = list(pager_obj) if isinstance(pager_obj, list) else []
    return {
        "kind": kind if kind != "ok" or items else ("empty" if kind == "ok" else kind),
        "items": items,
        "meta": {
            "found_text": str(meta.get("found_text") or "") or None,
            "pager_labels": pager_labels,
            "observed_page_size": len(items),
        },
    }


def normalize_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize detail extractor output into an allowlisted DTO."""
    kind = str(payload.get("kind") or "invalid")
    raw_obj = payload.get("content")
    raw: dict[str, Any] = raw_obj if isinstance(raw_obj, dict) else {}
    if kind != "ok":
        return {"kind": kind, "content": None}
    merged: dict[str, Any] = dict(raw)
    merged["url"] = canonicalize_vacancy_url(str(raw.get("url") or ""))
    content: HhVacancyDetail = allowlist_detail(merged)
    if not content.get("external_id") or not content.get("title"):
        return {"kind": "invalid", "content": None}
    if content.get("url") is None:
        content["url"] = f"https://hh.ru/vacancy/{content['external_id']}"
    return {"kind": "ok", "content": content}


def extract_search_page(page: Any) -> dict[str, Any]:
    """Run SERP allowlist extract on a Playwright page."""
    final_url = str(getattr(page, "url", "") or "")
    path = urlparse(final_url).path.lower()
    if "/account/login" in path or path == "/login":
        return {"kind": "login_required", "items": [], "meta": {}}
    payload = page.evaluate(SEARCH_EXTRACT_JS)
    if not isinstance(payload, dict):
        return {"kind": "invalid", "items": [], "meta": {}}
    return payload


def extract_detail_page(page: Any) -> dict[str, Any]:
    """Run detail allowlist extract on a Playwright page."""
    final_url = str(getattr(page, "url", "") or "")
    path = urlparse(final_url).path.lower()
    if "/account/login" in path or path == "/login":
        return {"kind": "login_required", "content": {}}
    payload = page.evaluate(DETAIL_EXTRACT_JS)
    if not isinstance(payload, dict):
        return {"kind": "invalid", "content": {}}
    return payload
