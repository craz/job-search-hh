"""Bounded Core HTTP client for idempotent vacancy and application writes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class CoreError(Exception):
    """Stable failure when Core is unreachable or rejects a write."""


class CoreGateway(Protocol):
    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def list_vacancies(self) -> list[dict[str, Any]]: ...

    def create_application(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...


class CoreClient:
    """Write vacancies/applications only through Core's versioned HTTP contract."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        final_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            final_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=final_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise CoreError(f"http_{error.code}:{detail}") from error
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise CoreError(str(error)) from error
        if not isinstance(result, dict):
            raise CoreError("invalid_core_response")
        return result

    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """Create or replay one vacancy under a mandatory Idempotency-Key."""
        return self._request(
            "POST",
            "/api/v1/vacancies",
            payload=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    def list_vacancies(self) -> list[dict[str, Any]]:
        """Return Core vacancies for HH identity resolution."""
        result = self._request("GET", "/api/v1/vacancies")
        items = result.get("items")
        if not isinstance(items, list):
            raise CoreError("invalid_core_response")
        return [item for item in items if isinstance(item, dict)]

    def find_vacancy(self, *, source: str, external_id: str) -> dict[str, Any] | None:
        """Locate one vacancy by provider identity without PostgreSQL access."""
        for item in self.list_vacancies():
            if item.get("source") == source and str(item.get("external_id")) == external_id:
                return item
        return None

    def create_application(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """Create or replay one application under a mandatory Idempotency-Key."""
        return self._request(
            "POST",
            "/api/v1/applications",
            payload=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
