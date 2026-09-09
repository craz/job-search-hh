"""Persistent HH state/profile paths, browser detection and operator auth markers."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from job_search_hh.browser import (
    DEFAULT_LOGIN_URL,
    BrowserError,
    BrowserLauncher,
    PlaywrightBrowserLauncher,
)
from job_search_hh.egress import egress_preflight_code


class SessionError(Exception):
    """Stable failure for session/profile scaffold boundaries."""


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionPaths:
    """HH-owned runtime directories for profile and private state."""

    state_dir: Path
    profile_dir: Path

    @classmethod
    def from_env(cls) -> SessionPaths:
        state = Path(os.getenv("HH_STATE_DIR", os.getenv("JOB_SEARCH_HH_STATE_DIR", ".hh-state")))
        profile = Path(
            os.getenv("HH_PROFILE_DIR", os.getenv("JOB_SEARCH_HH_PROFILE_DIR", ".hh-profile"))
        )
        return cls(state_dir=state, profile_dir=profile)

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    @property
    def session_marker(self) -> Path:
        return self.state_dir / "session.json"


def _profile_chrome_running(profile_dir: Path) -> bool:
    """True when a Chromium/Chrome process still references this profile dir."""
    try:
        listed = subprocess.run(
            ["ps", "-eo", "args"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    marker = str(profile_dir)
    for line in (listed.stdout or "").splitlines():
        low = line.casefold()
        if marker not in line:
            continue
        if "chrome" in low or "chromium" in low:
            return True
    return False


class ProfileLock:
    """File lock that prevents concurrent use of one Chromium profile."""

    def __init__(self, profile_dir: Path) -> None:
        self.path = profile_dir / ".profile.lock"
        self.profile_dir = profile_dir

    def status(self) -> str:
        if not self.path.parent.exists():
            return "missing"
        if self.path.exists():
            return "locked"
        return "unlocked"

    def acquire(self, owner: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise SessionError("profile_locked")
        self.path.write_text(json.dumps({"owner": owner}, ensure_ascii=False), encoding="utf-8")

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def release_orphaned(self) -> bool:
        """Drop a leftover lock when no Chromium still holds the profile."""
        if not self.path.exists():
            return False
        if _profile_chrome_running(self.profile_dir):
            return False
        self.release()
        return True


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def chromium_installed() -> bool:
    """Detect Chromium binary or an image that marked the install complete."""
    if _env_flag("HH_CHROMIUM_INSTALLED"):
        return True
    return any(
        shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "chrome")
    )


def novnc_public_url() -> str:
    """Loopback URL that opens the interactive HH desktop (not a directory listing)."""
    port = int(os.getenv("HH_NOVNC_PORT", "6080"))
    return f"http://127.0.0.1:{port}/vnc.html?autoconnect=1&resize=scale"


def novnc_configured() -> bool:
    """Detect noVNC web assets and explicit enablement for the runtime."""
    if not _env_flag("HH_NOVNC_ENABLED"):
        return False
    web = Path(os.getenv("HH_NOVNC_WEB", "/usr/share/novnc"))
    return web.exists()


def interactive_display_ready(*, timeout: float = 1.0) -> bool:
    """True when local x11vnc accepts connections (noVNC websocket backend)."""
    port = int(os.getenv("HH_VNC_PORT", "5900"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def require_interactive_login_runtime() -> None:
    """Fail fast with stable codes when operator login cannot become usable."""
    preflight = egress_preflight_code()
    if preflight:
        raise SessionError(preflight)
    if not novnc_configured():
        raise SessionError("novnc_unavailable")
    if not interactive_display_ready():
        raise SessionError("novnc_unavailable")


def browser_automation_level() -> str:
    """Return scaffold until Chromium+noVNC are present; never claim write-ready."""
    if chromium_installed() and novnc_configured():
        return "installed"
    return "scaffold"


def read_auth_session(paths: SessionPaths) -> str:
    """Read the operator-facing session marker without dumping cookies or tokens."""
    marker = paths.session_marker
    if not marker.exists():
        return "absent"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        status = str(payload.get("status") or "").strip()
        return status or "invalid"
    except (OSError, ValueError):
        return "invalid"


def write_auth_session(paths: SessionPaths, status: str, *, source: str) -> None:
    """Persist a non-secret session marker under the HH state volume."""
    paths.ensure()
    payload = {
        "status": status,
        "source": source,
        "updated_at": _utc_now(),
    }
    paths.session_marker.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def session_status(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Describe browser/auth runtime without launching HH login."""
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    lock = ProfileLock(resolved.profile_dir)
    auth_session = read_auth_session(resolved)
    level = browser_automation_level()
    return {
        "browser_automation": level,
        "chromium_installed": chromium_installed(),
        "playwright_installed": _module_available("playwright"),
        "novnc_configured": novnc_configured(),
        "novnc_port": int(os.getenv("HH_NOVNC_PORT", "6080")),
        "profile_dir": str(resolved.profile_dir.resolve()),
        "state_dir": str(resolved.state_dir.resolve()),
        "profile_lock": lock.status(),
        "auth_session": auth_session,
        "external_writes_enabled": False,
    }


def auth_status(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Return auth session marker; login_ready only after operator confirm."""
    status = session_status(paths)
    ready = status["auth_session"] == "present" and bool(status["chromium_installed"])
    return {
        "auth_session": status["auth_session"],
        "login_ready": ready,
        "novnc_configured": status["novnc_configured"],
        "browser_automation": status["browser_automation"],
        "novnc_port": status["novnc_port"],
    }


def open_login(
    paths: SessionPaths | None = None,
    *,
    login_url: str = DEFAULT_LOGIN_URL,
    detach: bool = False,
    launcher: BrowserLauncher | None = None,
) -> dict[str, Any]:
    """Open HH login in headed Chromium for noVNC; never solves CAPTCHA."""
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    if not chromium_installed():
        raise SessionError("chromium_missing")
    # Detached operator path needs a live VNC/noVNC stack; unit tests inject a launcher.
    if detach or launcher is None:
        require_interactive_login_runtime()
    lock = ProfileLock(resolved.profile_dir)
    lock.release_orphaned()
    report: dict[str, Any] = {
        "auth_session": "pending_operator",
        "browser_started": False,
        "detached": detach,
        "login_url": login_url,
        "novnc_url": novnc_public_url(),
        "profile_lock": lock.status(),
        "captcha_bypass": False,
        "interactive_ready": interactive_display_ready() if detach or launcher is None else True,
    }
    if detach:
        write_auth_session(resolved, "pending_operator", source="auth_open_login")
        from job_search_hh.browser import _clear_stale_chromium_singleton

        _clear_stale_chromium_singleton(resolved.profile_dir)
        log_path = resolved.state_dir / "login-browser.log"
        log_handle = log_path.open("w", encoding="utf-8")
        # Child takes the profile lock in foreground mode.
        child = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "job_search_hh.cli",
                "auth",
                "open-login",
                "--foreground",
                "--login-url",
                login_url,
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
        (resolved.state_dir / "login-browser.pid").write_text(str(child.pid), encoding="utf-8")
        # Detached spawn used to claim success while Chromium died on a stale
        # SingletonLock — verify the child is still alive briefly.
        time.sleep(2.5)
        if child.poll() is not None:
            detail = ""
            with contextlib.suppress(OSError):
                detail = log_path.read_text(encoding="utf-8")[-400:]
            if "profile_locked" in detail:
                raise SessionError("profile_locked")
            if "novnc_unavailable" in detail:
                raise SessionError("novnc_unavailable")
            raise SessionError("browser_launch_failed")
        report["browser_started"] = True
        report["pid"] = child.pid
        report["profile_lock"] = lock.status()
        return report

    lock.acquire("auth-open-login")
    write_auth_session(resolved, "pending_operator", source="auth_open_login")
    report["profile_lock"] = "locked"
    active = launcher or PlaywrightBrowserLauncher()
    try:
        active.open_login_page(profile_dir=resolved.profile_dir, login_url=login_url)
        report["browser_started"] = True
    except BrowserError as error:
        raise SessionError(str(error)) from error
    finally:
        lock.release()
        report["profile_lock"] = lock.status()
    return report


def _probe_browser_login_kind(paths: SessionPaths) -> str:
    """Return resumes-page kind for the persistent profile, or ``skipped``.

    Used by ``confirm_login`` so an unauthenticated browser cannot flip Job
    Search into ``connected`` merely because the operator clicked confirm.
    Probe failures are skipped (do not block a known-good OAuth path).
    """
    if not chromium_installed():
        return "skipped"
    try:
        from job_search_hh.resumes import DEFAULT_RESUMES_URL, _read_resumes_page
    except ImportError:
        return "skipped"
    try:
        lock = ProfileLock(paths.profile_dir)
        lock.acquire("confirm-login-probe")
        try:
            raw = _read_resumes_page(
                profile_dir=paths.profile_dir,
                resumes_url=DEFAULT_RESUMES_URL,
                timeout_ms=45_000,
            )
        finally:
            lock.release()
    except Exception:  # noqa: BLE001 - probe must not crash confirm
        return "skipped"
    if not isinstance(raw, dict):
        return "skipped"
    kind = str(raw.get("kind") or "skipped")
    return kind if kind else "skipped"


def confirm_login(
    paths: SessionPaths | None = None,
    *,
    confirmed: bool,
    login_probe: Any | None = None,
) -> dict[str, Any]:
    """Record operator confirmation that interactive HH login succeeded.

    Stops a detached login browser (if still running) so the profile lock is
    released and later read-only resume scraping can reuse the same profile.
    Best-effort OAuth refresh runs when a refresh_token is present so connection
    status can become ``connected`` instead of staying ``expired``.

    When the browser profile is still on a login wall, stays
    ``pending_operator`` (does not claim success).
    """
    if not confirmed:
        raise SessionError("confirmation_required")
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    _stop_detached_login_browser(resolved)

    prior_session = read_auth_session(resolved)
    browser_kind = "skipped"
    should_probe = login_probe is not None or prior_session == "pending_operator"
    if should_probe:
        probe = login_probe if login_probe is not None else _probe_browser_login_kind
        try:
            browser_kind = str(probe(resolved) or "skipped")
        except Exception:  # noqa: BLE001
            browser_kind = "skipped"
    if browser_kind in {"login_required", "captcha_or_action_required"}:
        write_auth_session(resolved, "pending_operator", source="confirm_login_incomplete")
        report = auth_status(resolved)
        report["token_refresh"] = "skipped"
        report["browser_login"] = browser_kind
        report["code"] = (
            "browser_login_incomplete"
            if browser_kind == "login_required"
            else "browser_captcha_or_action_required"
        )
        return report

    write_auth_session(resolved, "present", source="operator_confirm")
    token_refresh = "skipped"
    try:
        from job_search_hh.oauth import refresh_token_record, token_status

        tokens = token_status(resolved)
        if tokens.get("refresh_token_present") and tokens.get("expired"):
            refresh_token_record(resolved)
            token_refresh = "refreshed"
        elif tokens.get("access_token_present") and not tokens.get("expired"):
            token_refresh = "fresh"
        elif not tokens.get("access_token_present"):
            token_refresh = "missing"
    except Exception:  # noqa: BLE001 - never fail confirm on optional OAuth refresh
        token_refresh = "failed"
    report = auth_status(resolved)
    report["token_refresh"] = token_refresh
    report["browser_login"] = browser_kind
    return report


def _stop_detached_login_browser(paths: SessionPaths) -> None:
    """Best-effort stop of ``auth open-login --detach`` child; never dumps secrets."""
    pid_path = paths.state_dir / "login-browser.pid"
    if not pid_path.exists():
        ProfileLock(paths.profile_dir).release()
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid > 0:
        with contextlib.suppress(OSError):
            os.kill(pid, 15)
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
    with contextlib.suppress(OSError):
        pid_path.unlink()
    ProfileLock(paths.profile_dir).release()


def clear_login(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Remove the session marker without deleting the Chromium profile."""
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    if resolved.session_marker.exists():
        resolved.session_marker.unlink()
    return auth_status(resolved)
