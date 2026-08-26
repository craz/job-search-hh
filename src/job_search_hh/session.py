"""Persistent HH state/profile paths, browser detection and operator auth markers."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
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


class ProfileLock:
    """File lock that prevents concurrent use of one Chromium profile."""

    def __init__(self, profile_dir: Path) -> None:
        self.path = profile_dir / ".profile.lock"

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


def novnc_configured() -> bool:
    """Detect noVNC web assets and explicit enablement for the runtime."""
    if not _env_flag("HH_NOVNC_ENABLED"):
        return False
    web = Path(os.getenv("HH_NOVNC_WEB", "/usr/share/novnc"))
    return web.exists()


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
    novnc_port = int(os.getenv("HH_NOVNC_PORT", "6080"))
    report: dict[str, Any] = {
        "auth_session": "pending_operator",
        "browser_started": False,
        "detached": detach,
        "login_url": login_url,
        "novnc_url": f"http://127.0.0.1:{novnc_port}/",
        "profile_lock": ProfileLock(resolved.profile_dir).status(),
        "captcha_bypass": False,
    }
    if detach:
        write_auth_session(resolved, "pending_operator", source="auth_open_login")
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                **os.environ,
                "HH_STATE_DIR": str(resolved.state_dir),
                "HH_PROFILE_DIR": str(resolved.profile_dir),
            },
        )
        (resolved.state_dir / "login-browser.pid").write_text(str(child.pid), encoding="utf-8")
        report["browser_started"] = True
        report["pid"] = child.pid
        return report

    lock = ProfileLock(resolved.profile_dir)
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


def confirm_login(
    paths: SessionPaths | None = None,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    """Record operator confirmation that interactive HH login succeeded.

    Stops a detached login browser (if still running) so the profile lock is
    released and later read-only resume scraping can reuse the same profile.
    """
    if not confirmed:
        raise SessionError("confirmation_required")
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    _stop_detached_login_browser(resolved)
    write_auth_session(resolved, "present", source="operator_confirm")
    return auth_status(resolved)


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
