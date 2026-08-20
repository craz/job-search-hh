"""Bounded Core HTTP client for idempotent vacancy writes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class CoreError(Exception):
    """Stable failure when Core is unreachable or rejects a vacancy write."""


class CoreGateway(Protocol):
    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...


class CoreClient:
    """Write vacancies only through Core's versioned HTTP contract."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def create_vacancy(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """Create or replay one vacancy under a mandatory Idempotency-Key."""
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/vacancies",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            method="POST",
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
