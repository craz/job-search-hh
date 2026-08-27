"""Read-only HH resume detail content extract (R2.1.2 / TECH-US-01.3).

Uses the same authenticated Chromium profile as the resume list. Allowlist-only
field extraction — never stores contacts/phone/email/cookies/tokens.
Does **not** write to Core (that is R2.1.3).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from job_search_hh.connection import connection_status
from job_search_hh.recovery import with_recovery
from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    novnc_public_url,
)

DEFAULT_RESUME_URL_TEMPLATE = "https://hh.ru/resume/{external_id}"
EXTRACTOR_VERSION = "hh-browser-ro-v1"

STATUS_AVAILABLE = "available"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_PERMISSION_BLOCKED = "permission_blocked"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ACTION_REQUIRED = "action_required"

ResumeDetailReader = Callable[..., dict[str, Any]]

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{8,}\d)")

# Keep in sync with Core resume_snapshot allowlist (R2.1.1).
_CONTENT_ALLOWLIST = frozenset(
    {
        "title",
        "desired_position",
        "about",
        "skills",
        "experience",
        "education",
        "languages",
        "salary",
        "location",
        "employment_preferences",
    }
)
_NESTED_ALLOWLIST = {
    "experience": frozenset({"company", "position", "period", "description"}),
    "education": frozenset({"institution", "degree", "year"}),
    "languages": frozenset({"name", "level"}),
    "salary": frozenset({"text", "amount", "currency"}),
    "employment_preferences": frozenset({"text"}),
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _novnc_url() -> str:
    return novnc_public_url()


def _scrub_pii(text: str) -> str:
    """Defense-in-depth: strip emails/phones from allowlisted text fields."""
    cleaned = _EMAIL_RE.sub("", text)
    cleaned = _PHONE_RE.sub("", cleaned)
    return " ".join(cleaned.split()).strip()


def _scrub_content(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in content.items():
        if key not in _CONTENT_ALLOWLIST:
            continue
        if isinstance(value, str):
            scrubbed = _scrub_pii(value)
            if scrubbed:
                out[key] = scrubbed
        elif isinstance(value, list) and key == "skills":
            skills = [_scrub_pii(item) for item in value if isinstance(item, str)]
            skills = [item for item in skills if item]
            if skills:
                out[key] = skills
        elif isinstance(value, list):
            nested_keys = _NESTED_ALLOWLIST.get(key, frozenset())
            items: list[dict[str, str]] = []
            for raw in value:
                if not isinstance(raw, dict):
                    continue
                item = {
                    k: _scrub_pii(v)
                    for k, v in raw.items()
                    if isinstance(k, str)
                    and k in nested_keys
                    and isinstance(v, str)
                    and _scrub_pii(v)
                }
                if item:
                    items.append(item)
            if items:
                out[key] = items
        elif isinstance(value, dict):
            nested_keys = _NESTED_ALLOWLIST.get(key, frozenset())
            nested = {
                k: _scrub_pii(v)
                for k, v in value.items()
                if isinstance(k, str) and k in nested_keys and isinstance(v, str) and _scrub_pii(v)
            }
            if nested:
                out[key] = nested
    return out


def _extract_from_detail_page(page: Any) -> dict[str, Any]:
    """Allowlist extract scoring-relevant fields from an owner resume page."""
    final_url = str(page.url or "")
    path = urlparse(final_url).path.lower()
    if "/account/login" in path or path == "/login":
        return {"kind": "login_required", "content": {}}

    payload = page.evaluate(
        """() => {
          const text = (el) =>
            el ? (el.textContent || '').trim().replace(/\\s+/g, ' ') : '';
          const qa = (sel) => document.querySelector(sel);
          const qas = (sel) => Array.from(document.querySelectorAll(sel));

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

          const content = {};
          const title = text(qa('[data-qa="resume-block-title-position"]'));
          if (title) {
            content.title = title;
            content.desired_position = title;
          }

          const aboutCard = qa('[data-qa="resume-about-card"]');
          if (aboutCard) {
            const aboutClone = aboutCard.cloneNode(true);
            aboutClone.querySelectorAll(
              'button, [data-qa^="resume-edit"], svg'
            ).forEach((n) => n.remove());
            const about = text(aboutClone).replace(/^о себе\\s*/i, '').trim();
            if (about.length > 2) content.about = about;
          }

          const skillRoot = qa('[data-qa="skills-card"]') || document;
          const skillNodes = skillRoot.querySelectorAll(
            '[data-qa^="skill-tag-"], [data-qa="bloko-tag__text"]'
          );
          const skills = [];
          const seenSkills = new Set();
          for (const node of skillNodes) {
            const s = text(node);
            if (!s || s.length < 2 || seenSkills.has(s)) continue;
            if (/ключ|навык|редактир|добавить/i.test(s)) continue;
            seenSkills.add(s);
            skills.push(s);
          }
          if (skills.length) content.skills = skills;

          const experience = [];
          for (const card of qas('[data-qa="profile-experience-company-card"]')) {
            const clone = card.cloneNode(true);
            clone.querySelectorAll(
              'button, [data-qa^="edit-"], svg'
            ).forEach((n) => n.remove());
            const company =
              text(clone.querySelector('[data-qa*="company"]')) ||
              text(clone.querySelector('a[href*="employer"]')) ||
              '';
            const position =
              text(clone.querySelector('[data-qa*="position"]')) ||
              text(clone.querySelector('h3, h2, [class*="title"]')) ||
              '';
            const period =
              text(clone.querySelector(
                '[data-qa*="period"], [data-qa*="interval"], time'
              )) ||
              '';
            let description = text(clone);
            const parts = description
              .split(/\\s{2,}/)
              .map((p) => p.trim())
              .filter(Boolean);
            if (parts.length > 1) {
              description = parts.slice(1).join(' ');
            }
            const item = {};
            if (company) item.company = company;
            if (position) item.position = position;
            if (period) item.period = period;
            if (description && description.length > 10) {
              item.description = description;
            }
            if (Object.keys(item).length) experience.push(item);
          }
          if (experience.length) content.experience = experience;

          const education = [];
          for (const node of qas(
            '[data-qa^="resume-list-card-education-item-"], ' +
            '[data-qa="resume-list-card-education"] li, ' +
            '[data-qa*="education-item"]'
          )) {
            const line = text(node);
            if (!line || line.length < 3) continue;
            if (/образован|редактир|добавить/i.test(line) && line.length < 40) {
              continue;
            }
            education.push({ institution: line });
          }
          if (education.length) content.education = education;

          const languages = [];
          for (const node of qas(
            '[data-qa="resume-block-language-item"], ' +
            '[data-qa*="language-item"]'
          )) {
            const line = text(node);
            if (!line || line.length < 2) continue;
            languages.push({ name: line });
          }
          if (languages.length) content.languages = languages;

          const salary = text(qa('[data-qa="resume-block-salary"]'));
          if (salary) {
            const cleaned = salary.replace(/^зарплат[аы]?\\s*/i, '').trim();
            content.salary = { text: cleaned || salary };
          }

          const relocation = text(qa('[data-qa="resume-block-relocation"]'));
          if (relocation) content.location = relocation;

          const prefs = text(qa(
            '[data-qa="resume-block-specialization"], ' +
            '[data-qa="resume-block-employment"]'
          ));
          if (prefs) content.employment_preferences = { text: prefs };

          if (!Object.keys(content).length) {
            return { kind: 'empty', content: {} };
          }
          return { kind: 'ok', content };
        }"""
    )
    if not isinstance(payload, dict):
        return {"kind": "invalid", "content": {}}
    kind = str(payload.get("kind") or "invalid")
    raw_content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    return {"kind": kind, "content": raw_content}


def _read_resume_detail_page(
    *,
    profile_dir: Any,
    resume_url: str,
    timeout_ms: int,
) -> dict[str, Any]:
    """Open persistent Chromium profile and extract one resume detail page."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover
        raise SessionError("playwright_missing") from error

    display = (os.getenv("DISPLAY") or os.getenv("HH_DISPLAY") or "").strip()
    env: dict[str, str | float | bool] = {key: value for key, value in os.environ.items()}
    if display:
        env["DISPLAY"] = display

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            env=env if display else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(resume_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(2_500, max(500, timeout_ms // 20)))
            return _extract_from_detail_page(page)
        finally:
            context.close()


def read_resume_content(
    external_resume_id: str,
    paths: SessionPaths | None = None,
    *,
    page_reader: ResumeDetailReader | None = None,
    timeout_seconds: float = 45.0,
    resume_url_template: str = DEFAULT_RESUME_URL_TEMPLATE,
) -> dict[str, Any]:
    """Return allowlisted resume content envelope for one own HH resume id."""
    return with_recovery(
        _read_resume_content_raw(
            external_resume_id,
            paths,
            page_reader=page_reader,
            timeout_seconds=timeout_seconds,
            resume_url_template=resume_url_template,
        )
    )


def _read_resume_content_raw(
    external_resume_id: str,
    paths: SessionPaths | None = None,
    *,
    page_reader: ResumeDetailReader | None = None,
    timeout_seconds: float = 45.0,
    resume_url_template: str = DEFAULT_RESUME_URL_TEMPLATE,
) -> dict[str, Any]:
    resolved = paths or SessionPaths.from_env()
    checked_at = _utc_now()
    external_id = (external_resume_id or "").strip()
    connection = connection_status(resolved)
    connection_state = str(connection.get("status") or STATUS_UNAVAILABLE)
    auth = auth_status(resolved)
    base: dict[str, Any] = {
        "external_resume_id": external_id or None,
        "source": "hh",
        "transport": "browser_readonly",
        "extractor_version": EXTRACTOR_VERSION,
        "content": None,
        "connection_status": connection_state,
        "login_ready": bool(auth.get("login_ready")),
        "checked_at": checked_at,
        "captured_at": None,
        "action": {"code": "none"},
    }
    if not external_id or len(external_id) < 6:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "invalid_resume_id",
        }

    if not auth.get("login_ready"):
        return {
            **base,
            "status": STATUS_NOT_AUTHORIZED,
            "code": "browser_login_required",
            "action": {"code": "open_login", "novnc_url": _novnc_url()},
        }

    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "profile_locked",
            "action": {"code": "confirm_login", "novnc_url": _novnc_url()},
        }

    resume_url = resume_url_template.format(external_id=external_id)
    reader = page_reader or _read_resume_detail_page
    try:
        lock.acquire("resume-content")
        try:
            raw = reader(
                profile_dir=resolved.profile_dir,
                resume_url=resume_url,
                timeout_ms=int(timeout_seconds * 1000),
            )
        finally:
            lock.release()
    except SessionError as error:
        return {**base, "status": STATUS_UNAVAILABLE, "code": str(error)}
    except Exception:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "browser_resume_read_failed",
        }

    if not isinstance(raw, dict):
        return {**base, "status": STATUS_UNAVAILABLE, "code": "invalid_resume_page"}

    kind = str(raw.get("kind") or "")
    if kind == "login_required":
        return {
            **base,
            "status": STATUS_NOT_AUTHORIZED,
            "code": "browser_session_not_logged_in",
            "action": {"code": "open_login", "novnc_url": _novnc_url()},
        }
    if kind == "captcha_or_action_required":
        return {
            **base,
            "status": STATUS_ACTION_REQUIRED,
            "code": "browser_captcha_or_action_required",
            "action": {"code": "confirm_login", "novnc_url": _novnc_url()},
        }
    if kind == "permission_blocked":
        return {
            **base,
            "status": STATUS_PERMISSION_BLOCKED,
            "code": "browser_resume_forbidden",
        }
    if kind not in {"ok", "empty"}:
        return {**base, "status": STATUS_UNAVAILABLE, "code": "invalid_resume_page"}

    raw_content_obj = raw.get("content")
    raw_content: dict[str, Any] = raw_content_obj if isinstance(raw_content_obj, dict) else {}
    content = _scrub_content(raw_content)
    if not content:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "resume_content_empty",
            "content": None,
        }
    captured_at = _utc_now()
    return {
        **base,
        "status": STATUS_AVAILABLE,
        "code": "ready",
        "content": content,
        "captured_at": captured_at,
    }
