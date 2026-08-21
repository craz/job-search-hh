"""Read-only HH vacancy and authenticated negotiation providers."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


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


def _negotiation_state_id(item: dict[str, Any]) -> str:
    state = item.get("state")
    if isinstance(state, dict):
        return str(state.get("id") or "").strip().casefold()
    return str(state or "").strip().casefold()


def _flatten_negotiation(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize HH API negotiation documents toward fixture-compatible shape."""
    flat = dict(item)
    state = item.get("state")
    if isinstance(state, dict) and state.get("id") is not None:
        flat["state"] = state.get("id")
    return flat


class AuthenticatedHhApi:
    """Bearer-authenticated HH GET client for negotiations; never POSTs to HH."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        access_token: str,
        *,
        max_pages: int = 5,
    ) -> None:
        if not access_token.strip():
            raise ProviderError("access_token_missing")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._access_token = access_token.strip()
        self.max_pages = max(1, min(max_pages, 20))

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self._access_token}",
        }

    def _get_json(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        base = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
            raise ProviderError("invalid_hh_url")
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise ProviderError(f"http_{error.code}") from error
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise ProviderError(str(error)) from error
        if not isinstance(payload, dict):
            raise ProviderError("invalid_hh_response")
        return payload

    def _collect_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        direct = payload.get("items")
        if isinstance(direct, list):
            return [_flatten_negotiation(item) for item in direct if isinstance(item, dict)]

        collected: list[dict[str, Any]] = []
        collections = payload.get("collections")
        if not isinstance(collections, list):
            return collected
        for collection in collections:
            if not isinstance(collection, dict):
                continue
            nested = collection.get("items")
            if isinstance(nested, list):
                collected.extend(
                    _flatten_negotiation(item) for item in nested if isinstance(item, dict)
                )
                continue
            url = collection.get("url")
            if isinstance(url, str) and url.strip():
                collected.extend(self._paginate(url.strip()))
        return collected

    def _next_page_url(self, current_url: str, payload: dict[str, Any]) -> str | None:
        next_link = payload.get("next") or payload.get("next_url")
        if isinstance(next_link, str) and next_link.strip():
            return next_link.strip()
        pages_meta = payload.get("pages")
        page = payload.get("page")
        if not (isinstance(pages_meta, int) and isinstance(page, int) and page + 1 < pages_meta):
            return None
        parsed = urllib.parse.urlparse(current_url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        params["page"] = str(page + 1)
        if "per_page" not in params:
            params["per_page"] = "50"
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(params)))

    def _paginate(self, first_url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = first_url
        pages = 0
        while next_url and pages < self.max_pages:
            payload = self._get_json(next_url)
            page_items = payload.get("items")
            if isinstance(page_items, list):
                items.extend(
                    _flatten_negotiation(item) for item in page_items if isinstance(item, dict)
                )
            pages += 1
            next_url = self._next_page_url(next_url, payload)
        return items

    def list_applications(self) -> list[dict[str, Any]]:
        """GET applicant negotiations only; never POST /negotiations."""
        url = f"{self.base_url}/negotiations?{urllib.parse.urlencode({'per_page': 50, 'page': 0})}"
        payload = self._get_json(url)
        items = self._collect_from_payload(payload)
        if items:
            return items
        return self._paginate(url)

    def list_metrics(self) -> list[dict[str, Any]]:
        """Derive one UTC daily snapshot from negotiations GET (no HH stats write)."""
        applications = self.list_applications()
        metric_date = datetime.now(UTC).date().isoformat()
        replies = sum(
            1 for item in applications if _negotiation_state_id(item) in {"response", "reply"}
        )
        invitations = sum(
            1 for item in applications if _negotiation_state_id(item) in {"invitation", "interview"}
        )
        rejections = sum(
            1 for item in applications if _negotiation_state_id(item) in {"discard", "rejected"}
        )
        return [
            {
                "metric_date": metric_date,
                "applications": len(applications),
                "replies": replies,
                "invitations": invitations,
                "rejections": rejections,
                "notes": "derived_from_negotiations_get",
            }
        ]
