"""Product-facing HH own-resume list via authenticated browser (R1.3).

Official GET /resumes/mine remains EXTERNAL_BLOCKED. This module uses the
operator Chromium profile (read-only navigation) and returns a normalized
resume-summary contract: external_id + title only.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from job_search_hh.connection import connection_status
from job_search_hh.session import (
    ProfileLock,
    SessionError,
    SessionPaths,
    auth_status,
    novnc_public_url,
)

DEFAULT_RESUMES_URL = "https://hh.ru/applicant/resumes"

STATUS_AVAILABLE = "available"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_PERMISSION_BLOCKED = "permission_blocked"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ACTION_REQUIRED = "action_required"

ResumePageReader = Callable[..., dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _novnc_url() -> str:
    return novnc_public_url()


def _clean_resume_title(title: str) -> str:
    """Keep the human resume name; drop HH card chrome glued into textContent."""
    cleaned = " ".join((title or "").split())
    if not cleaned:
        return ""
    # Truncate at known bump / auto-raise / edit chrome (RU + EN).
    cut_markers = (
        "Поднять вручную",
        "Подключено автоподнятие",
        "Автоподнятие",
        "автоподнятие",
        "Дополнить резюме",
        "Обновить дату",
        "Raise manually",
        "Auto-raise",
    )
    cut_at = len(cleaned)
    for marker in cut_markers:
        idx = cleaned.find(marker)
        if idx != -1:
            cut_at = min(cut_at, idx)
    return cleaned[:cut_at].strip(" ·|-–—")


def _normalize_items(raw_items: list[Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        external_id = raw.get("external_id")
        title = raw.get("title")
        if not isinstance(external_id, str) or not isinstance(title, str):
            continue
        external_id = external_id.strip()
        title = _clean_resume_title(title)
        if not external_id or not title or external_id in seen:
            continue
        if len(external_id) < 6:
            continue
        seen.add(external_id)
        items.append({"external_id": external_id, "title": title})
    return items


def _extract_from_page(page: Any) -> dict[str, Any]:
    """Extract resume summaries or login/permission signals from a Playwright page."""
    final_url = str(page.url or "")
    path = urlparse(final_url).path.lower()
    if "/account/login" in path or path == "/login":
        return {"kind": "login_required", "items": []}

    payload = page.evaluate(
        """() => {
          const login = document.querySelector(
            '[data-qa="account-login-form"], [data-qa="applicant-login-card"], [data-qa="login"]'
          );
          if (login) {
            return { kind: 'login_required', items: [] };
          }
          const forbidden = document.querySelector(
            '[data-qa="error-forbidden"], [data-qa="vacancy-forbidden"]'
          );
          if (forbidden) {
            return { kind: 'permission_blocked', items: [] };
          }
          const items = [];
          const seen = new Set();

          const cards = Array.from(document.querySelectorAll('[data-qa^="resume-card-link-"]'));
          const collectFrom = cards.length
            ? cards
            : Array.from(document.querySelectorAll('a[href*="/resume/"]'));

          for (const node of collectFrom) {
            const href = node.getAttribute('href') || '';
            const match = href.match(/\\/resume\\/([0-9A-Za-z_-]{6,})/);
            if (!match) continue;
            const id = match[1];
            if (seen.has(id)) continue;

            const root = node.closest('[data-qa*="resume"], article, li, section, div') || node;
            const titleNode =
              root.querySelector('[data-qa="resume-title"]') ||
              root.querySelector('h3[data-qa="title"], [data-qa="title"]') ||
              null;
            let title = titleNode
              ? (titleNode.textContent || '').trim().replace(/\\s+/g, ' ')
              : '';
            if (!title) {
              title = (node.textContent || '').trim().replace(/\\s+/g, ' ');
            }
            if (!title || title.length < 2) continue;
            if (/cookie|footer|политик|blog|expert|^дополнить резюме$/i.test(title)) continue;
            seen.add(id);
            items.push({ external_id: id, title });
          }
          return { kind: 'ok', items };
        }"""
    )
    if not isinstance(payload, dict):
        return {"kind": "invalid", "items": []}
    kind = str(payload.get("kind") or "invalid")
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {"kind": kind, "items": items}


def _read_resumes_page(
    *,
    profile_dir: Any,
    resumes_url: str,
    timeout_ms: int,
) -> dict[str, Any]:
    """Open persistent Chromium profile, navigate read-only, extract resume list."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover - host without playwright
        raise SessionError("playwright_missing") from error

    display = (os.getenv("DISPLAY") or os.getenv("HH_DISPLAY") or "").strip()
    env: dict[str, str | float | bool] = {key: value for key, value in os.environ.items()}
    if display:
        env["DISPLAY"] = display

    with sync_playwright() as playwright:
        # Read-only scrape does not need a visible window; headless avoids X/noVNC races
        # while still loading the persistent operator profile cookies.
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            env=env if display else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(resumes_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(2_500, max(500, timeout_ms // 20)))
            return _extract_from_page(page)
        finally:
            context.close()


def list_resumes(
    paths: SessionPaths | None = None,
    *,
    resumes_url: str = DEFAULT_RESUMES_URL,
    page_reader: ResumePageReader | None = None,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Return normalized own-resume list using browser session (not official API)."""
    checked_at = _utc_now()
    resolved = paths or SessionPaths.from_env()
    connection = connection_status(resolved)
    connection_state = str(connection.get("status") or STATUS_UNAVAILABLE)
    auth = auth_status(resolved)
    base: dict[str, Any] = {
        "items": [],
        "connection_status": connection_state,
        "login_ready": bool(auth.get("login_ready")),
        "checked_at": checked_at,
        "transport": "browser_readonly",
        "action": {"code": "none"},
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

    reader = page_reader or _read_resumes_page
    try:
        lock.acquire("resumes-list")
        try:
            raw = reader(
                profile_dir=resolved.profile_dir,
                resumes_url=resumes_url,
                timeout_ms=int(timeout_seconds * 1000),
            )
        finally:
            lock.release()
    except SessionError as error:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": str(error),
        }
    except Exception:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "browser_resume_read_failed",
        }

    if not isinstance(raw, dict):
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "invalid_resume_page",
        }

    kind = str(raw.get("kind") or "")
    if kind == "login_required":
        return {
            **base,
            "status": STATUS_NOT_AUTHORIZED,
            "code": "browser_session_not_logged_in",
            "action": {"code": "open_login", "novnc_url": _novnc_url()},
        }
    if kind == "permission_blocked":
        return {
            **base,
            "status": STATUS_PERMISSION_BLOCKED,
            "code": "browser_resume_forbidden",
        }
    if kind not in {"ok", "empty"}:
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": "invalid_resume_page",
        }

    items = _normalize_items(list(raw.get("items") or []))
    return {
        **base,
        "status": STATUS_AVAILABLE,
        "items": items,
        "code": "ready" if items else "empty",
    }


def parse_resume_href(href: str) -> str | None:
    """Extract resume external_id from an HH resume URL (tests / helpers)."""
    match = re.search(r"/resume/([0-9A-Za-z_-]{6,})", href or "")
    return match.group(1) if match else None
