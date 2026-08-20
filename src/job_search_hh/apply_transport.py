"""Apply transports that never perform live HH writes in dry-run mode."""

from __future__ import annotations

from typing import Any, Protocol


class ApplyTransportError(Exception):
    """Reject unsafe or incomplete apply transport usage."""


class ApplyTransport(Protocol):
    def submit(self, intent: dict[str, Any]) -> dict[str, Any]: ...


class FakeApplyTransport:
    """Record planned HH writes without contacting HeadHunter."""

    WRITE_PATH = "/negotiations"

    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self.write_attempted = False

    def submit(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Append one dry-run audit entry and return a non-submitted status."""
        if intent.get("live") is True:
            self.write_attempted = True
            raise ApplyTransportError("live_apply_forbidden")
        path = str(intent.get("path") or self.WRITE_PATH)
        if not path.startswith("/"):
            self.write_attempted = True
            raise ApplyTransportError("absolute_hh_url_forbidden")
        entry = {
            "method": "POST",
            "path": path,
            "body_keys": sorted(str(key) for key in intent.get("body", {})),
            "vacancy_external_id": intent.get("vacancy_external_id"),
            "resume_id": intent.get("resume_id"),
            "message_chars": len(str(intent.get("message") or "")),
        }
        self.audit.append(entry)
        return {"status": "dry-run", "would_send": entry}
