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
        }
    return {
        "screenshot_available": True,
        "screenshot_filename": filename,
        "screenshot_path": str(target),
        "screenshot_bytes": target.stat().st_size if target.is_file() else 0,
    }


def write_challenge_state(
    *,
    challenge_url: str,
    challenge_title: str = "",
    run_id: str | None = None,
    vacancy_id: str | None = None,
    progress: dict[str, Any] | None = None,
    screenshot: dict[str, Any] | None = None,
    paths: SessionPaths | None = None,
) -> dict[str, Any]:
    resolved = paths or SessionPaths.from_env()
    shot = screenshot or {}
    state = {
        "status": "operator_action_required",
        "code": "browser_captcha_or_action_required",
        "detected_at": _utc_now(),
        "challenge_url": challenge_url,
        "challenge_title": challenge_title,
        "run_id": run_id,
        "vacancy_id": vacancy_id,
        "progress": progress or {},
        "screenshot_available": bool(shot.get("screenshot_available")),
        "screenshot_filename": shot.get("screenshot_filename"),
        "challenge_session_available": False,
        "handoff_pid": None,
        "novnc_url": novnc_public_url() if novnc_configured() else None,
        "note": (
            "Challenge was captured in headless scraper context. "
            "Manual recovery opens headed Chromium at the challenge URL on the "
            "same persistent profile — not a fresh login page."
        ),
    }
    challenge_state_path(resolved).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return state


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
    """Open headed Chromium at the challenge URL on the persistent profile (noVNC)."""
    resolved = paths or SessionPaths.from_env()
    state = read_challenge_state(resolved) or {}
    url = (challenge_url or state.get("challenge_url") or "").strip()
    if not url:
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
            "DISPLAY": os.getenv("HH_DISPLAY") or os.getenv("DISPLAY") or ":99",
            "HH_DISPLAY": os.getenv("HH_DISPLAY") or os.getenv("DISPLAY") or ":99",
        },
    )
    log_handle.close()
    (resolved.state_dir / "challenge-browser.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(2.5)
    if child.poll() is not None:
        detail = ""
        with contextlib.suppress(OSError):
            detail = log_path.read_text(encoding="utf-8")[-400:]
        if "profile_locked" in detail:
            raise SessionError("profile_locked")
        raise SessionError("browser_launch_failed")

    state = dict(state)
    state["challenge_session_available"] = True
    state["handoff_pid"] = child.pid
    state["handoff_opened_at"] = _utc_now()
    state["novnc_url"] = novnc_public_url()
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
        "detached": detach,
    }


def confirm_challenge_cleared(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Re-check challenge URL; clear state only when challenge is gone."""
    resolved = paths or SessionPaths.from_env()
    state = read_challenge_state(resolved)
    if not state:
        return {
            "ok": True,
            "cleared": True,
            "code": "no_active_challenge",
            "challenge": None,
        }
    url = str(state.get("challenge_url") or "").strip()
    if not url:
        clear_challenge_state(resolved)
        return {"ok": True, "cleared": True, "code": "ready", "challenge": None}

    from job_search_hh.session import ProfileLock, chromium_installed

    if not chromium_installed():
        return {
            "ok": False,
            "cleared": False,
            "code": "chromium_missing",
            "challenge": state,
        }
    lock = ProfileLock(resolved.profile_dir)
    if lock.status() == "locked":
        return {
            "ok": False,
            "cleared": False,
            "code": "profile_locked",
            "challenge": state,
            "message": "Закройте браузер challenge в noVNC, затем нажмите «Проверить снова».",
        }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SessionError("playwright_missing") from error

    still_challenged = False
    final_url = url
    title = ""
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
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1_500)
                final_url = str(page.url or "")
                try:
                    title = str(page.title() or "")
                except Exception:  # noqa: BLE001
                    title = ""
                still_challenged = looks_like_hh_challenge(url=final_url, title=title)
                if not still_challenged:
                    try:
                        from job_search_hh.vacancy_extractors import _CHALLENGE_DOM_JS

                        still_challenged = bool(page.evaluate(_CHALLENGE_DOM_JS))
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                context.close()
    finally:
        lock.release()

    if still_challenged:
        state["last_probe_at"] = _utc_now()
        state["last_probe_url"] = final_url
        state["last_probe_title"] = title
        challenge_state_path(resolved).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "ok": False,
            "cleared": False,
            "code": "browser_captcha_or_action_required",
            "challenge": state,
            "message": "CAPTCHA всё ещё активна.",
        }

    clear_challenge_state(resolved)
    return {
        "ok": True,
        "cleared": True,
        "code": "ready",
        "challenge": None,
        "probed_url": final_url,
        "message": "Challenge снят. Можно снова запустить проверку подходящих.",
    }


def begin_challenge_handoff(
    *,
    challenge_url: str,
    challenge_title: str = "",
    run_id: str | None = None,
    vacancy_id: str | None = None,
    progress: dict[str, Any] | None = None,
    screenshot: dict[str, Any] | None = None,
    paths: SessionPaths | None = None,
    auto_open_browser: bool = True,
) -> dict[str, Any]:
    """Persist evidence, optional Telegram notify, optionally open headed challenge."""
    state = write_challenge_state(
        challenge_url=challenge_url,
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
    if auto_open_browser and interactive_display_ready() and novnc_configured():
        try:
            open_report = open_challenge_browser(challenge_url=challenge_url, paths=paths)
            opened = bool(open_report.get("browser_started"))
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
    return {
        "challenge": state,
        "telegram": notify,
        "challenge_session_available": bool(state.get("challenge_session_available")),
        "browser_auto_opened": opened,
        "action": {
            "code": ACTION_OPEN_CHALLENGE,
            "novnc_url": state.get("novnc_url")
            or (novnc_public_url() if novnc_configured() else None),
            "challenge_url": challenge_url,
        },
    }


def public_challenge_view(paths: SessionPaths | None = None) -> dict[str, Any] | None:
    """Safe challenge payload for Web (no absolute host paths)."""
    state = read_challenge_state(paths)
    if not state:
        return None
    return {
        "status": state.get("status"),
        "code": state.get("code"),
        "detected_at": state.get("detected_at"),
        "challenge_url": state.get("challenge_url"),
        "challenge_title": state.get("challenge_title"),
        "run_id": state.get("run_id"),
        "vacancy_id": state.get("vacancy_id"),
        "progress": state.get("progress") or {},
        "screenshot_available": bool(state.get("screenshot_available")),
        "challenge_session_available": bool(state.get("challenge_session_available")),
        "novnc_url": state.get("novnc_url"),
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
