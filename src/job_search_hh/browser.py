"""HH browser launch for operator login over the shared X/noVNC display."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

DEFAULT_LOGIN_URL = "https://hh.ru/account/login"


class BrowserError(Exception):
    """Browser launch failures without dumping profile or cookie contents."""


class BrowserLauncher(Protocol):
    """Minimal launcher surface so unit tests avoid real Chromium."""

    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        """Open HH login in a headed browser bound to the persistent profile."""


def _clear_stale_chromium_singleton(profile_dir: Path) -> None:
    """Drop leftover Singleton* locks when no Chromium process holds the profile.

    After container recreate the profile volume keeps SingletonLock pointing at a
    dead host/pid; headed Chromium then exits immediately and noVNC stays black.
    """
    lock = profile_dir / "SingletonLock"
    socket = profile_dir / "SingletonSocket"
    if not lock.exists() and not socket.exists():
        return
    # If a chrome process is alive for this profile, leave the lock alone.
    try:
        listed = subprocess.run(
            ["ps", "-eo", "pid,cmd"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        haystack = listed.stdout or ""
        marker = str(profile_dir)
        if "chrome" in haystack and marker in haystack:
            return
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        path = profile_dir / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except OSError:
            continue


class PlaywrightBrowserLauncher:
    """Launch headed Playwright Chromium against the HH profile directory."""

    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - host without playwright
            raise BrowserError("playwright_missing") from error

        profile_dir.mkdir(parents=True, exist_ok=True)
        _clear_stale_chromium_singleton(profile_dir)
        display = (os.getenv("HH_DISPLAY") or os.getenv("DISPLAY") or "").strip()
        if not display:
            raise BrowserError("display_missing")
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=False,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--window-size=1280,720",
                        "--window-position=0,0",
                    ],
                    env={**os.environ, "DISPLAY": display},
                    ignore_default_args=["--enable-automation"],
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(login_url, wait_until="domcontentloaded", timeout=90_000)
                except Exception:
                    # Keep a visible window on the noVNC desktop instead of a black screen.
                    page.set_content(
                        "<h1>Не удалось открыть HeadHunter</h1>"
                        "<p>Проверьте сеть Job Search и нажмите «Войти в HeadHunter» ещё раз.</p>"
                    )
                # Operator interacts via noVNC; closing the window ends the session.
                while context.pages:
                    try:
                        context.pages[0].wait_for_event("close", timeout=3_600_000)
                    except Exception:
                        break
                context.close()
        except BrowserError:
            raise
        except Exception as error:  # pragma: no cover - runtime browser failures
            raise BrowserError("browser_launch_failed") from error
