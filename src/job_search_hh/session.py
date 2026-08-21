"""Persistent HH state/profile paths, browser detection and profile lock."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SessionError(Exception):
    """Stable failure for session/profile scaffold boundaries."""


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


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
    """Return scaffold until Chromium+noVNC are present; never claim login-ready."""
    if chromium_installed() and novnc_configured():
        return "installed"
    return "scaffold"


def session_status(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Describe browser/auth runtime without launching HH login."""
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    lock = ProfileLock(resolved.profile_dir)
    session_marker = resolved.state_dir / "session.json"
    auth_session = "absent"
    if session_marker.exists():
        try:
            payload = json.loads(session_marker.read_text(encoding="utf-8"))
            status = str(payload.get("status") or "").strip()
            if status:
                auth_session = status
        except (OSError, ValueError):
            auth_session = "invalid"
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
    """Return auth session marker without performing HH login."""
    status = session_status(paths)
    return {
        "auth_session": status["auth_session"],
        "login_ready": False,
        "novnc_configured": status["novnc_configured"],
        "browser_automation": status["browser_automation"],
    }
