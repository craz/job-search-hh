"""Persist HH CAPTCHA challenge evidence and operator same-profile handoff.

Scraper uses headless Chromium on the persistent profile; noVNC login opens a
*separate* headed Chromium at /account/login. Challenge evidence must be captured
from the scraper page before that context closes. Manual recovery opens headed
Chromium at the *challenge URL* (not login) so the owner can see the same gate
when HH still binds it to the profile/session.

Telegram notify is optional and only runs when TELEGRAM_DM_* + HH_CAPTCHA_TG are set.
Screenshots live under HH_STATE_DIR (private runtime) and must never be committed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from job_search_hh.session import (
    SessionError,
    SessionPaths,
    interactive_display_ready,
    novnc_configured,
    novnc_public_url,
    require_interactive_login_runtime,
)
from job_search_hh.vacancy_extractors import looks_like_hh_challenge

logger = logging.getLogger(__name__)

CHALLENGE_STATE_NAME = "challenge_active.json"
CHALLENGE_DIR_NAME = "challenges"
ACTION_OPEN_CHALLENGE = "open_challenge"
ACTION_CONFIRM_CHALLENGE = "confirm_challenge"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().casefold() in {"1", "true", "yes", "on"}


def captcha_tg_configured() -> bool:
    """True when owner explicitly enabled CAPTCHA Telegram notify with DM credentials."""
    if not _env_flag("HH_CAPTCHA_TG"):
        return False
    token = (os.getenv("TELEGRAM_DM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_DM_CHAT_ID") or "").strip()
    return bool(token and chat)


def challenge_state_path(paths: SessionPaths | None = None) -> Path:
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    return resolved.state_dir / CHALLENGE_STATE_NAME


def challenge_dir(paths: SessionPaths | None = None) -> Path:
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    path = resolved.state_dir / CHALLENGE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_challenge_state(paths: SessionPaths | None = None) -> dict[str, Any] | None:
    path = challenge_state_path(paths)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_challenge_state(paths: SessionPaths | None = None) -> None:
    path = challenge_state_path(paths)
    with contextlib.suppress(OSError):
        path.unlink()


# Capture classes for operator recovery UX:
# A — URL + screenshot; B — URL, screenshot failed; C — captcha seen, handoff capture failed.
CAPTURE_OK = "captured"  # A
CAPTURE_NO_SCREENSHOT = "captured_no_screenshot"  # B
CAPTURE_FAILED = "capture_failed"  # C
ACTION_CHALLENGE_CAPTURE_FAILED = "challenge_capture_failed"
# Bumped when capture/handoff contract changes; written into challenge_active.
CAPTURE_IMPL_ID = "capture-v2-persist-before-close"


def classify_capture(*, challenge_url: str, screenshot: dict[str, Any] | None) -> str:
    """Return capture class A/B/C code for challenge_active state."""
    url = (challenge_url or "").strip()
    shot = screenshot or {}
    if not url:
        return CAPTURE_FAILED
    if shot.get("screenshot_available"):
        return CAPTURE_OK
    return CAPTURE_NO_SCREENSHOT


def recovery_available_from_state(
    state: dict[str, Any] | None, *, url_fallback: str = ""
) -> bool:
    """True when operator noVNC recovery may be offered.

    Legacy states (pre-capture-v2) omit ``recovery_available``; infer from URL so
    Web/API never strip a real challenge_url after a code upgrade.
    """
    if not state:
        return bool((url_fallback or "").strip())
    if "recovery_available" in state and state.get("recovery_available") is not None:
        return bool(state.get("recovery_available"))
    url = str(state.get("challenge_url") or url_fallback or "").strip()
    return bool(url)


def capture_challenge_screenshot(page: Any, *, paths: SessionPaths | None = None) -> dict[str, Any]:
    """Capture PNG from the live challenged Playwright page into private state."""
    resolved = paths or SessionPaths.from_env()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"captcha-{stamp}.png"
    target = challenge_dir(resolved) / filename
    try:
        page.screenshot(path=str(target), full_page=False)
    except Exception as error:  # noqa: BLE001 - evidence is best-effort
        return {
            "screenshot_available": False,
            "screenshot_error": type(error).__name__,
            "screenshot_error_detail": str(error)[:240],
        }
    return {
        "screenshot_available": True,
        "screenshot_filename": filename,
        "screenshot_path": str(target),
        "screenshot_bytes": target.stat().st_size if target.is_file() else 0,
    }


def write_challenge_state(
    *,
    challenge_url: str = "",
    challenge_title: str = "",
    run_id: str | None = None,
    vacancy_id: str | None = None,
    progress: dict[str, Any] | None = None,
    screenshot: dict[str, Any] | None = None,
    paths: SessionPaths | None = None,
    capture_status: str | None = None,
) -> dict[str, Any]:
    resolved = paths or SessionPaths.from_env()
    shot = screenshot or {}
    url = (challenge_url or "").strip()
    status = capture_status or classify_capture(challenge_url=url, screenshot=shot)
    recovery_available = status in {CAPTURE_OK, CAPTURE_NO_SCREENSHOT} and bool(url)
    state = {
        "status": "operator_action_required",
        "code": "browser_captcha_or_action_required",
        "detected_at": _utc_now(),
        "challenge_url": url or None,
        "challenge_title": challenge_title,
        "run_id": run_id,
        "vacancy_id": vacancy_id,
        "progress": progress or {},
        "screenshot_available": bool(shot.get("screenshot_available")),
        "screenshot_filename": shot.get("screenshot_filename"),
        "screenshot_error": shot.get("screenshot_error"),
        "screenshot_error_detail": shot.get("screenshot_error_detail"),
        "capture_status": status,
        "recovery_available": recovery_available,
        "capture_impl": CAPTURE_IMPL_ID,
        "challenge_session_available": False,
        "handoff_pid": None,
        "novnc_url": (
            novnc_public_url() if recovery_available and novnc_configured() else None
        ),
        "note": (
            "Challenge was captured in headless scraper context. "
            "Manual recovery opens headed Chromium at the challenge URL on the "
            "same persistent profile — not a fresh login page."
            if recovery_available
            else (
                "CAPTCHA was detected but challenge URL/screenshot could not be "
                "persisted for noVNC recovery. Retry acquisition after checking HH."
            )
        ),
    }
    challenge_state_path(resolved).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return state


def capture_and_persist_live_challenge(
    page: Any,
    *,
    challenge_url_hint: str | None = None,
    run_id: str | None = None,
    vacancy_id: str | None = None,
    progress: dict[str, Any] | None = None,
    paths: SessionPaths | None = None,
) -> dict[str, Any]:
    """Atomically capture URL/title/screenshot and persist state while page is live.

    Must run before Playwright ``context.close`` and before terminal status raise.
    Never fabricates a challenge URL.
    """
    resolved = paths or SessionPaths.from_env()
    url = (challenge_url_hint or "").strip()
    if not url:
        try:
            url = str(getattr(page, "url", "") or "").strip()
        except Exception:  # noqa: BLE001
            url = ""
    title = ""
    try:
        title = str(page.title() or "")
    except Exception as error:  # noqa: BLE001
        title = ""
        title_error = type(error).__name__
    else:
        title_error = None

    screenshot: dict[str, Any]
    try:
        screenshot = capture_challenge_screenshot(page, paths=resolved)
    except Exception as error:  # noqa: BLE001
        screenshot = {
            "screenshot_available": False,
            "screenshot_error": type(error).__name__,
            "screenshot_error_detail": str(error)[:240],
        }

    state = write_challenge_state(
        challenge_url=url,
        challenge_title=title,
        run_id=run_id,
        vacancy_id=vacancy_id,
        progress=progress,
        screenshot=screenshot,
        paths=resolved,
    )
    if title_error and not state.get("screenshot_error"):
        state["title_error"] = title_error
        challenge_state_path(resolved).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    logger.info(
        "hh_captcha_capture impl=%s status=%s url_present=%s screenshot=%s "
        "vacancy_id=%s run_id=%s shot_error=%s",
        CAPTURE_IMPL_ID,
        state.get("capture_status"),
        bool(url),
        bool(state.get("screenshot_available")),
        vacancy_id,
        run_id,
        screenshot.get("screenshot_error"),
    )
    return {
        "challenge_url": url,
        "challenge_title": title,
        "screenshot": screenshot,
        "challenge": state,
        "recovery_available": bool(state.get("recovery_available")),
        "capture_status": state.get("capture_status"),
        "capture_impl": CAPTURE_IMPL_ID,
    }

def notify_challenge_telegram(state: dict[str, Any]) -> dict[str, Any]:
    """Best-effort DM notify when explicitly configured; never invents credentials."""
    if not captcha_tg_configured():
        return {"notified": False, "reason": "telegram_not_configured"}
    token = (os.getenv("TELEGRAM_DM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_DM_CHAT_ID") or "").strip()
    progress = state.get("progress") if isinstance(state.get("progress"), dict) else {}
    pages = progress.get("pages_fetched")
    planned = progress.get("pages_planned")
    checked = progress.get("checked_count")
    lines = [
        "HeadHunter требует CAPTCHA",
        f"время: {state.get('detected_at') or '—'}",
    ]
    if pages is not None and planned is not None:
        lines.append(f"страниц HH: {pages}/{planned}")
    if checked is not None:
        lines.append(f"проверено: {checked}")
    if state.get("vacancy_id"):
        lines.append(f"vacancy: {state['vacancy_id']}")
    lines.append("Откройте recovery UI Job Search и браузер challenge (не «Войти»).")
    caption = "\n".join(lines)
    try:
        import urllib.request

        boundary = f"----jsBoundary{int(time.time())}"
        shot_name = state.get("screenshot_filename")
        shot_path = None
        if shot_name:
            candidate = challenge_dir() / str(shot_name)
            if candidate.is_file():
                shot_path = candidate

        def _multipart(fields: dict[str, str], file_field: tuple[str, bytes, str] | None) -> bytes:
            body = bytearray()
            for key, value in fields.items():
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body.extend(str(value).encode("utf-8"))
                body.extend(b"\r\n")
            if file_field is not None:
                name, content, filename = file_field
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(
                    (
                        f'Content-Disposition: form-data; name="{name}"; '
                        f'filename="{filename}"\r\n'
                        "Content-Type: image/png\r\n\r\n"
                    ).encode()
                )
                body.extend(content)
                body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            return bytes(body)

        if shot_path is not None:
            data = _multipart(
                {"chat_id": chat, "caption": caption},
                ("photo", shot_path.read_bytes(), shot_path.name),
            )
            endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
            kind = "photo"
        else:
            data = _multipart(
                {
                    "chat_id": chat,
                    "text": caption,
                    "disable_web_page_preview": "true",
                },
                None,
            )
            endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
            kind = "message"
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            resp.read()
        return {"notified": True, "channel": "telegram_dm", "kind": kind}
    except Exception as error:  # noqa: BLE001 - notify must not abort handoff
        return {"notified": False, "reason": type(error).__name__}


def open_challenge_browser(
    *,
    challenge_url: str | None = None,
    paths: SessionPaths | None = None,
    detach: bool = True,
) -> dict[str, Any]:
    """Open headed Chromium at the challenge URL on the persistent profile (noVNC).

    Returns ``interactive_ready=true`` only when the headed process stays alive on
    DISPLAY :99 and VNC accepts connections. Websocket-only noVNC is not success.
    """
    resolved = paths or SessionPaths.from_env()
    state = read_challenge_state(resolved) or {}
    url = (challenge_url or state.get("challenge_url") or "").strip()
    if not url:
        raise SessionError("challenge_url_missing")
    if not recovery_available_from_state(state, url_fallback=url):
        raise SessionError("challenge_url_missing")
    if "/account/login" in url and "showcaptcha" not in url.casefold():
        raise SessionError("challenge_url_is_login")
    require_interactive_login_runtime()
    from job_search_hh.browser import _clear_stale_chromium_singleton
    from job_search_hh.session import ProfileLock

    lock = ProfileLock(resolved.profile_dir)
    lock.release_orphaned()
    if lock.status() == "locked":
        raise SessionError("profile_locked")

    display = os.getenv("HH_DISPLAY") or os.getenv("DISPLAY") or ":99"
    _clear_stale_chromium_singleton(resolved.profile_dir)
    log_path = resolved.state_dir / "challenge-browser.log"
    log_handle = log_path.open("w", encoding="utf-8")
    child = subprocess.Popen(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "job_search_hh.cli",
            "auth",
            "open-login",
            "--foreground",
            "--login-url",
            url,
        ],
        start_new_session=True,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "HH_STATE_DIR": str(resolved.state_dir),
            "HH_PROFILE_DIR": str(resolved.profile_dir),
            "DISPLAY": display,
            "HH_DISPLAY": display,
        },
    )
    log_handle.close()
    (resolved.state_dir / "challenge-browser.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(2.5)
    exit_code = child.poll()
    if exit_code is not None:
        detail = ""
        with contextlib.suppress(OSError):
            detail = log_path.read_text(encoding="utf-8")[-400:]
        if "profile_locked" in detail:
            raise SessionError("profile_locked")
        raise SessionError("browser_launch_failed")

    display_ready = interactive_display_ready()
    browser_alive = child.poll() is None
    interactive_ready = bool(display_ready and browser_alive)
    if not interactive_ready:
        with contextlib.suppress(ProcessLookupError, OSError):
            child.terminate()
        raise SessionError("interactive_not_ready")

    state = dict(state)
    state["challenge_session_available"] = True
    state["handoff_pid"] = child.pid
    state["handoff_opened_at"] = _utc_now()
    state["handoff_display"] = display
    state["novnc_url"] = novnc_public_url()
    state["interactive_ready"] = True
    challenge_state_path(resolved).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "action": {"code": ACTION_OPEN_CHALLENGE, "novnc_url": novnc_public_url()},
        "challenge": state,
        "pid": child.pid,
        "browser_started": True,
        "interactive_ready": True,
        "display": display,
        "detached": detach,
    }


def confirm_challenge_cleared(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Re-check challenge URL; clear state only when challenge is gone.

    If the headed challenge Chromium still holds the profile, refuse with an
    explicit operator message (do not probe and do not clear). Stale locks /
    Singleton leftovers are healed only when no Chromium still uses the profile.
    """
    resolved = paths or SessionPaths.from_env()
    state = read_challenge_state(resolved)
    if not state:
        return {
            "ok": True,
            "cleared": True,
            "code": "no_active_challenge",
            "challenge": None,
            "message": "Активного CAPTCHA challenge нет.",
        }
    url = str(state.get("challenge_url") or "").strip()
    if not url:
        clear_challenge_state(resolved)
        return {
            "ok": True,
            "cleared": True,
            "code": "ready",
            "challenge": None,
            "message": "CAPTCHA подтверждена, HeadHunter доступен",
        }

    from job_search_hh.browser import _clear_stale_chromium_singleton
    from job_search_hh.session import ProfileLock, _profile_chrome_running, chromium_installed

    if not chromium_installed():
        return {
            "ok": False,
            "cleared": False,
            "code": "chromium_missing",
            "challenge": public_challenge_view(resolved) or state,
            "message": "Chromium не установлен — проверку challenge выполнить нельзя.",
        }

    lock = ProfileLock(resolved.profile_dir)
    # Heal leftover product lock only when no Chromium still holds the profile.
    lock.release_orphaned()
    chrome_live = _profile_chrome_running(resolved.profile_dir)
    handoff_live = _challenge_handoff_process_alive(state, resolved)
    if chrome_live or handoff_live or lock.status() == "locked":
        # Keep state; owner must close the headed window in noVNC.
        return {
            "ok": False,
            "cleared": False,
            "code": "challenge_browser_open",
            "challenge": public_challenge_view(resolved) or state,
            "message": (
                "Окно CAPTCHA ещё открыто. "
                "Закройте браузер HeadHunter в noVNC и повторите проверку."
            ),
            "challenge_browser_open": True,
            "profile_lock": lock.status(),
            "chrome_running": chrome_live,
        }

    # Chromium closed: drop stale Singleton* so headless probe can open the profile.
    _clear_stale_chromium_singleton(resolved.profile_dir)
    with contextlib.suppress(OSError):
        (resolved.state_dir / "challenge-browser.pid").unlink()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SessionError("playwright_missing") from error

    still_challenged = False
    final_url = url
    title = ""
    probe_targets = _confirm_probe_urls(challenge_url=url)
    lock.acquire("challenge-confirm-probe")
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(resolved.profile_dir),
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                # Prefer backurl / resumes — captured captcha URLs are often one-shot.
                for target in probe_targets:
                    page.goto(target, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(1_500)
                    final_url = str(page.url or "")
                    try:
                        title = str(page.title() or "")
                    except Exception:  # noqa: BLE001
                        title = ""
                    challenged = looks_like_hh_challenge(url=final_url, title=title)
                    if not challenged:
                        try:
                            from job_search_hh.vacancy_extractors import _CHALLENGE_DOM_JS

                            challenged = bool(page.evaluate(_CHALLENGE_DOM_JS))
                        except Exception:  # noqa: BLE001
                            challenged = False
                    if challenged:
                        still_challenged = True
                        break
                    # Non-challenge page loaded — session is past the gate.
                    still_challenged = False
                    break
            finally:
                context.close()
    finally:
        lock.release()

    if still_challenged:
        state["last_probe_at"] = _utc_now()
        state["last_probe_url"] = final_url
        state["last_probe_title"] = title
        state["challenge_session_available"] = False
        state["handoff_pid"] = None
        challenge_state_path(resolved).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "ok": False,
            "cleared": False,
            "code": "browser_captcha_or_action_required",
            "challenge": public_challenge_view(resolved) or state,
            "message": "HeadHunter всё ещё требует подтверждение CAPTCHA",
            "probed_url": final_url,
            "probed_title": title,
        }

    clear_challenge_state(resolved)
    # Promote session / connection when the challenge gate is gone.
    confirm_report: dict[str, Any] = {}
    try:
        from job_search_hh.session import confirm_login

        confirm_report = confirm_login(resolved, confirmed=True)
    except SessionError as error:
        confirm_report = {"ok": False, "code": str(error)}
    except Exception as error:  # noqa: BLE001
        confirm_report = {"ok": False, "code": type(error).__name__}

    from job_search_hh.connection import connection_status

    connection = connection_status()
    login_ready = bool(connection.get("login_ready") or confirm_report.get("login_ready"))
    return {
        "ok": True,
        "cleared": True,
        "code": "ready",
        "challenge": None,
        "probed_url": final_url,
        "message": "CAPTCHA подтверждена, HeadHunter доступен",
        "login_ready": login_ready,
        "confirm_login": {
            "code": confirm_report.get("code") or confirm_report.get("status"),
            "login_ready": confirm_report.get("login_ready"),
            "status": confirm_report.get("status"),
        },
        "connection": connection,
    }


def _challenge_handoff_process_alive(
    state: dict[str, Any] | None,
    paths: SessionPaths,
) -> bool:
    """True when the headed challenge open-login child is still running."""
    candidates: list[int] = []
    if state and state.get("handoff_pid"):
        with contextlib.suppress(TypeError, ValueError):
            candidates.append(int(state["handoff_pid"]))
    pid_path = paths.state_dir / "challenge-browser.pid"
    if pid_path.is_file():
        with contextlib.suppress(OSError, ValueError):
            candidates.append(int(pid_path.read_text(encoding="utf-8").strip()))
    for pid in candidates:
        if pid <= 0:
            continue
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            continue
    return False


def _confirm_probe_urls(*, challenge_url: str) -> list[str]:
    """URLs to verify CAPTCHA is gone without relying on a one-shot captcha link."""
    from urllib.parse import parse_qs, unquote, urlparse

    urls: list[str] = []
    parsed = urlparse(challenge_url)
    back = (parse_qs(parsed.query).get("backurl") or [None])[0]
    if back:
        decoded = unquote(str(back)).strip()
        if decoded.startswith("http"):
            urls.append(decoded)
    urls.append("https://hh.ru/applicant/resumes")
    # Keep original last — only if earlier probes are unavailable.
    if challenge_url not in urls:
        urls.append(challenge_url)
    # De-dupe preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in urls:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def begin_challenge_handoff(
    *,
    challenge_url: str = "",
    challenge_title: str = "",
    run_id: str | None = None,
    vacancy_id: str | None = None,
    progress: dict[str, Any] | None = None,
    screenshot: dict[str, Any] | None = None,
    paths: SessionPaths | None = None,
    auto_open_browser: bool = False,
    existing_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist evidence, optional Telegram notify, optionally open headed challenge.

    Does not fabricate challenge URLs. Auto-open defaults off — owner opens noVNC
    only after explicit open-challenge reports interactive_ready.
    """
    url = (challenge_url or "").strip()
    if existing_state and isinstance(existing_state, dict):
        state = dict(existing_state)
        # Refresh progress/screenshot fields when finalize has more context.
        if progress:
            merged = dict(state.get("progress") or {})
            merged.update(progress)
            state["progress"] = merged
        if screenshot:
            state["screenshot_available"] = bool(screenshot.get("screenshot_available"))
            if screenshot.get("screenshot_filename"):
                state["screenshot_filename"] = screenshot.get("screenshot_filename")
            if screenshot.get("screenshot_error"):
                state["screenshot_error"] = screenshot.get("screenshot_error")
            state["capture_status"] = classify_capture(
                challenge_url=str(state.get("challenge_url") or url),
                screenshot=screenshot,
            )
            state["recovery_available"] = state["capture_status"] in {
                CAPTURE_OK,
                CAPTURE_NO_SCREENSHOT,
            } and bool(str(state.get("challenge_url") or url).strip())
        challenge_state_path(paths).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        state = write_challenge_state(
            challenge_url=url,
            challenge_title=challenge_title,
            run_id=run_id,
            vacancy_id=vacancy_id,
            progress=progress,
            screenshot=screenshot,
            paths=paths,
        )
    notify = notify_challenge_telegram(state)
    opened = False
    open_error = None
    effective_url = str(state.get("challenge_url") or url).strip()
    if "recovery_available" not in state or state.get("recovery_available") is None:
        state["recovery_available"] = recovery_available_from_state(
            state, url_fallback=effective_url
        )
        state["capture_status"] = state.get("capture_status") or classify_capture(
            challenge_url=effective_url,
            screenshot={
                "screenshot_available": state.get("screenshot_available"),
                "screenshot_error": state.get("screenshot_error"),
            },
        )
        state["capture_impl"] = state.get("capture_impl") or CAPTURE_IMPL_ID
    recovery = recovery_available_from_state(state, url_fallback=effective_url)
    state["recovery_available"] = recovery
    if (
        auto_open_browser
        and recovery
        and effective_url
        and interactive_display_ready()
        and novnc_configured()
    ):
        try:
            open_report = open_challenge_browser(challenge_url=effective_url, paths=paths)
            opened = bool(
                open_report.get("browser_started") and open_report.get("interactive_ready")
            )
            state = open_report.get("challenge") or read_challenge_state(paths) or state
        except SessionError as error:
            open_error = str(error)
        except Exception as error:  # noqa: BLE001
            open_error = type(error).__name__
    state["telegram"] = notify
    if open_error:
        state["handoff_error"] = open_error
    challenge_state_path(paths).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if recovery and effective_url:
        action: dict[str, Any] = {
            "code": ACTION_OPEN_CHALLENGE,
            "novnc_url": state.get("novnc_url")
            or (novnc_public_url() if novnc_configured() else None),
            "challenge_url": effective_url,
        }
    else:
        action = {
            "code": ACTION_CHALLENGE_CAPTURE_FAILED,
            "novnc_url": None,
            "challenge_url": None,
        }
    return {
        "challenge": state,
        "telegram": notify,
        "challenge_session_available": bool(state.get("challenge_session_available")),
        "browser_auto_opened": opened,
        "recovery_available": recovery,
        "action": action,
    }


def public_challenge_view(paths: SessionPaths | None = None) -> dict[str, Any] | None:
    """Safe challenge payload for Web (no absolute host paths)."""
    state = read_challenge_state(paths)
    if not state:
        return None
    url = str(state.get("challenge_url") or "").strip() or None
    recovery = recovery_available_from_state(state, url_fallback=url or "")
    return {
        "status": state.get("status"),
        "code": state.get("code"),
        "detected_at": state.get("detected_at"),
        "challenge_url": url if recovery else None,
        "challenge_title": state.get("challenge_title"),
        "run_id": state.get("run_id"),
        "vacancy_id": state.get("vacancy_id"),
        "progress": state.get("progress") or {},
        "screenshot_available": bool(state.get("screenshot_available")),
        "screenshot_error": state.get("screenshot_error"),
        "capture_status": state.get("capture_status")
        or classify_capture(
            challenge_url=url or "",
            screenshot={"screenshot_available": state.get("screenshot_available")},
        ),
        "recovery_available": recovery,
        "capture_impl": state.get("capture_impl"),
        "challenge_session_available": bool(state.get("challenge_session_available")),
        "interactive_ready": bool(state.get("interactive_ready")),
        "novnc_url": state.get("novnc_url") if recovery else None,
        "note": state.get("note"),
        "telegram_notified": bool((state.get("telegram") or {}).get("notified")),
    }


def read_challenge_screenshot_bytes(
    paths: SessionPaths | None = None,
) -> tuple[bytes, str] | None:
    state = read_challenge_state(paths)
    if not state or not state.get("screenshot_filename"):
        return None
    path = challenge_dir(paths) / str(state["screenshot_filename"])
    if not path.is_file():
        return None
    return path.read_bytes(), path.name
