"""Read-only HH vacancy providers without apply or session side effects."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol


class ProviderError(Exception):
    """Stable failure for HH read transport problems."""


class VacancyProvider(Protocol):
    def search(self, *, text: str, per_page: int) -> list[dict[str, Any]]: ...


class ApplicationProvider(Protocol):
    def list_applications(self) -> list[dict[str, Any]]: ...


class MetricProvider(Protocol):
    def list_metrics(self) -> list[dict[str, Any]]: ...


class FixtureProvider:
    """Synthetic HH search hits for BDD and offline CLI use."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    @classmethod
    def from_path(cls, path: Path) -> FixtureProvider:
        """Load a JSON list or `{items: [...]}` document from disk."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ProviderError("invalid_fixture")
        return cls([item for item in items if isinstance(item, dict)])

    def search(self, *, text: str, per_page: int) -> list[dict[str, Any]]:
        del text
        return self.items[: max(per_page, 0)]

    def list_applications(self) -> list[dict[str, Any]]:
        """Reuse the same fixture document shape for application sync."""
        return list(self.items)

    def list_metrics(self) -> list[dict[str, Any]]:
        """Reuse the same fixture document shape for daily metric sync."""
        return list(self.items)


class HttpHhApi:
    """Public HH vacancy search client; never submits applications."""

    def __init__(self, base_url: str, user_agent: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    def search(self, *, text: str, per_page: int) -> list[dict[str, Any]]:
        """Fetch one page of public vacancy search results."""
        query = urllib.parse.urlencode({"text": text, "per_page": max(1, min(per_page, 50))})
        request = urllib.request.Request(
            f"{self.base_url}/vacancies?{query}",
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise ProviderError(f"http_{error.code}") from error
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise ProviderError(str(error)) from error
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("invalid_hh_response")
        return [item for item in items if isinstance(item, dict)]
