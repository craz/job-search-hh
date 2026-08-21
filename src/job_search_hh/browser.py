"""HH browser launch for operator login over the shared X/noVNC display."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

DEFAULT_LOGIN_URL = "https://hh.ru/account/login"


class BrowserError(Exception):
    """Browser launch failures without dumping profile or cookie contents."""


class BrowserLauncher(Protocol):
    """Minimal launcher surface so unit tests avoid real Chromium."""

    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        """Open HH login in a headed browser bound to the persistent profile."""


class PlaywrightBrowserLauncher:
    """Launch headed Playwright Chromium against the HH profile directory."""

    def open_login_page(self, *, profile_dir: Path, login_url: str) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - host without playwright
            raise BrowserError("playwright_missing") from error

        profile_dir.mkdir(parents=True, exist_ok=True)
        display = os.getenv("DISPLAY", "").strip()
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=False,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    env={**os.environ, **({"DISPLAY": display} if display else {})},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(login_url, wait_until="domcontentloaded")
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
