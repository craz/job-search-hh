"""Download active HH resume via visible menu action «Скачать» (R2.1-CORR-01)."""

from __future__ import annotations

import mimetypes
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from job_search_hh.recovery import with_recovery
from job_search_hh.resume_content import _novnc_url
from job_search_hh.session import ProfileLock, SessionError, SessionPaths, auth_status

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_AUTHORIZED = "not_authorized"
STATUS_PERMISSION_BLOCKED = "permission_blocked"
STATUS_ACTION_REQUIRED = "action_required"

DOWNLOAD_EXTRACTOR_VERSION = "hh-browser-download-v1"
APPLICANT_PROFILE_URL = "https://hh.ru/applicant/profile/me"

DOWNLOAD_FORMAT_SELECTORS = (
    "operations-list-download-resume-pdf",
    "operations-list-download-resume-doc",
    "operations-list-download-resume-rtf",
    "operations-list-download-resume-txt",
)

ResumeDownloadReader = Callable[..., dict[str, Any]]

_FILENAME_SAFE_RE = re.compile(r"^[^/\\]+$")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _guess_mime(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _sanitize_filename(name: str) -> str:
    cleaned = Path(name).name.strip()
    if not cleaned or not _FILENAME_SAFE_RE.match(cleaned):
        return "resume"
    return cleaned


def _resume_card_locator(page: Any, external_resume_id: str) -> Any:
    by_link = page.locator(f'[data-qa="resume-card-link-{external_resume_id}"]')
    if by_link.count() > 0:
        return page.locator('[data-qa^="resume "]').filter(has=by_link).first
    highlighted = page.locator('[data-qa="resume resume-highlighted"]')
    if highlighted.count() > 0:
        return highlighted.first
    return page.locator('[data-qa^="resume "]').first


def _open_download_menu(page: Any, card: Any, *, timeout_ms: int) -> bool:
    more = card.locator('[data-qa="resume-list-action-more"]')
    if more.count() > 0:
        more.first.click(timeout=timeout_ms)
        return True
    for selector in (
        '[data-qa="resume-action-menu"]',
        'button[data-qa="resume-action-menu"]',
        'button[aria-label*="Действия"]',
        'button[aria-label*="действия"]',
    ):
        locator = page.locator(selector)
        if locator.count() > 0:
            locator.first.click(timeout=timeout_ms)
            return True
    more_button = page.get_by_role("button", name=re.compile(r"^\.\.\.$|ещё|еще", re.I))
    if more_button.count() > 0:
        more_button.first.click(timeout=timeout_ms)
        return True
    return False


def _click_visible_download_action(page: Any, *, timeout_ms: int) -> bool:
    download_action = page.locator('[data-qa="operations-list-download-resume"]')
    if download_action.count() > 0:
        download_action.first.click(timeout=timeout_ms)
        return True
    download_item = page.get_by_role("menuitem", name="Скачать")
    if download_item.count() == 0:
        download_item = page.locator('button:has-text("Скачать")')
    if download_item.count() == 0:
        download_item = page.get_by_text("Скачать", exact=True)
    if download_item.count() == 0:
        return False
    download_item.first.click(timeout=timeout_ms)
    return True


def _persist_playwright_download(download: Any) -> dict[str, Any]:
    suggested = download.suggested_filename or "resume"
    filename = _sanitize_filename(suggested)
    suffix = Path(filename).suffix or ""
    temp_dir = tempfile.mkdtemp(prefix="hh-resume-download-")
    temp_path = Path(temp_dir) / f"download{suffix}"
    try:
        download.save_as(str(temp_path))
        data = temp_path.read_bytes()
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        Path(temp_dir).rmdir()
    if not data:
        return {"kind": "empty"}
    return {
        "kind": "ok",
        "data": data,
        "original_filename": filename,
        "mime_type": _guess_mime(filename),
        "size_bytes": len(data),
    }


def _trigger_download_on_page(page: Any, *, external_resume_id: str, timeout_ms: int) -> dict[str, Any]:
    """Open resume «…» menu, choose visible «Скачать», then first offered format."""
    card = _resume_card_locator(page, external_resume_id)
    if card.count() == 0:
        return {"kind": "menu_missing"}
    if not _open_download_menu(page, card, timeout_ms=timeout_ms):
        return {"kind": "menu_missing"}
    page.wait_for_timeout(min(1_000, max(300, timeout_ms // 40)))
    if not _click_visible_download_action(page, timeout_ms=timeout_ms):
        return {"kind": "action_missing"}
    page.wait_for_timeout(min(1_000, max(300, timeout_ms // 40)))

    for selector in DOWNLOAD_FORMAT_SELECTORS:
        format_button = page.locator(f'[data-qa="{selector}"]')
        if format_button.count() == 0:
            continue
        try:
            with page.expect_download(timeout=timeout_ms) as download_info:
                format_button.first.click(timeout=timeout_ms)
            return _persist_playwright_download(download_info.value)
        except Exception:
            continue

    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            page.locator('[data-qa="operations-list-download-resume"]').first.click(timeout=timeout_ms)
        return _persist_playwright_download(download_info.value)
    except Exception:
        return {"kind": "action_missing"}


def _download_resume_file_page(
    *,
    profile_dir: Any,
    external_resume_id: str,
    timeout_ms: int,
) -> dict[str, Any]:
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
            page.goto(APPLICANT_PROFILE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(2_500, max(500, timeout_ms // 20)))
            return _trigger_download_on_page(
                page,
                external_resume_id=external_resume_id,
                timeout_ms=timeout_ms,
            )
        finally:
            context.close()


def download_resume_file(
    external_resume_id: str,
    paths: SessionPaths | None = None,
    *,
    page_reader: ResumeDownloadReader | None = None,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Download resume file via HH UI action «Скачать»; no hidden API."""
    return with_recovery(
        _download_resume_file_raw(
            external_resume_id,
            paths,
            page_reader=page_reader,
            timeout_seconds=timeout_seconds,
        )
    )


def _download_resume_file_raw(
    external_resume_id: str,
    paths: SessionPaths | None = None,
    *,
    page_reader: ResumeDownloadReader | None = None,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    resolved = paths or SessionPaths.from_env()
    checked_at = _utc_now()
    external_id = (external_resume_id or "").strip()
    auth = auth_status(resolved)
    base: dict[str, Any] = {
        "external_resume_id": external_id or None,
        "source": "hh",
        "transport": "browser_readonly",
        "extractor_version": DOWNLOAD_EXTRACTOR_VERSION,
        "checked_at": checked_at,
        "action": {"code": "none"},
    }
    if not external_id:
        return {**base, "status": STATUS_UNAVAILABLE, "code": "missing_resume_id", "ok": False}
    if not auth.get("login_ready"):
        return {
            **base,
            "status": STATUS_NOT_AUTHORIZED,
            "code": "browser_login_required",
            "ok": False,
            "action": {"code": "open_login", "novnc_url": _novnc_url()},
        }

    timeout_ms = int(max(5.0, timeout_seconds) * 1000)
    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return {**base, "status": STATUS_UNAVAILABLE, "code": "profile_locked", "ok": False}
    try:
        lock.acquire("resume-download")
        try:
            if page_reader is not None:
                result = page_reader(
                    profile_dir=resolved.profile_dir,
                    external_resume_id=external_id,
                    timeout_ms=timeout_ms,
                )
            else:
                result = _download_resume_file_page(
                    profile_dir=resolved.profile_dir,
                    external_resume_id=external_id,
                    timeout_ms=timeout_ms,
                )
        finally:
            lock.release()
    except SessionError as error:
        return {**base, "status": STATUS_UNAVAILABLE, "code": str(error), "ok": False}

    kind = str(result.get("kind") or "invalid")
    if kind != "ok":
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "code": f"download_{kind}",
            "ok": False,
        }

    return {
        **base,
        "status": STATUS_AVAILABLE,
        "code": "downloaded",
        "ok": True,
        "original_filename": result.get("original_filename"),
        "mime_type": result.get("mime_type"),
        "size_bytes": result.get("size_bytes"),
        "captured_at": checked_at,
        "data": result.get("data"),
    }
