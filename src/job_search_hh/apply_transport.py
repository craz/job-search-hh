"""Apply transports: dry-run fake and gated live HH POST client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol
from urllib.parse import urlparse


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


class RecordingLiveApplyTransport:
    """Test double for gated live apply without opening a network socket."""

    WRITE_PATH = "/negotiations"

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.audit: list[dict[str, Any]] = []
        self.write_attempted = False
        self.fail_with = fail_with

    def submit(self, intent: dict[str, Any]) -> dict[str, Any]:
        if intent.get("live") is not True:
            raise ApplyTransportError("live_flag_required")
        path = str(intent.get("path") or self.WRITE_PATH)
        if path != self.WRITE_PATH:
            raise ApplyTransportError("unexpected_apply_path")
        self.write_attempted = True
        if self.fail_with:
            raise ApplyTransportError(self.fail_with)
        entry = {
            "method": "POST",
            "path": path,
            "body_keys": sorted(str(key) for key in intent.get("body", {})),
            "vacancy_external_id": intent.get("vacancy_external_id"),
            "resume_id": intent.get("resume_id"),
            "message_chars": len(str(intent.get("message") or "")),
        }
        self.audit.append(entry)
        return {
            "status": "submitted",
            "negotiation_id": f"neg-{intent.get('vacancy_external_id')}",
            "would_send": entry,
        }


class HttpApplyTransport:
    """POST /negotiations with Bearer token; never used unless dual-gated by caller."""

    WRITE_PATH = "/negotiations"

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        access_token: str,
    ) -> None:
        if not access_token.strip():
            raise ApplyTransportError("access_token_missing")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._access_token = access_token.strip()
        self.write_attempted = False
        self.audit: list[dict[str, Any]] = []

    def submit(self, intent: dict[str, Any]) -> dict[str, Any]:
        if intent.get("live") is not True:
            raise ApplyTransportError("live_flag_required")
        path = str(intent.get("path") or self.WRITE_PATH)
        if path != self.WRITE_PATH:
            raise ApplyTransportError("unexpected_apply_path")
        body = intent.get("body")
        if not isinstance(body, dict):
            raise ApplyTransportError("invalid_apply_body")
        vacancy_id = str(body.get("vacancy_id") or "").strip()
        resume_id = str(body.get("resume_id") or "").strip()
        if not vacancy_id or not resume_id:
            raise ApplyTransportError("incomplete_apply_body")

        url = f"{self.base_url}{path}"
        parsed = urlparse(url)
        base = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
            raise ApplyTransportError("invalid_hh_url")

        form = {
            "vacancy_id": vacancy_id,
            "resume_id": resume_id,
            "message": str(body.get("message") or ""),
        }
        entry = {
            "method": "POST",
            "path": path,
            "body_keys": sorted(form),
            "vacancy_external_id": intent.get("vacancy_external_id"),
            "resume_id": resume_id,
            "message_chars": len(form["message"]),
        }
        self.write_attempted = True
        self.audit.append(entry)
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
                "Authorization": f"Bearer {self._access_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", errors="replace")
            except OSError:
                detail = ""
            lowered = detail.casefold()
            if error.code in {403, 429} or "captcha" in lowered:
                raise ApplyTransportError("captcha_or_auth_stop") from error
            raise ApplyTransportError(f"http_{error.code}") from error
        except (OSError, urllib.error.URLError, ValueError) as error:
            raise ApplyTransportError("apply_transport_failed") from error

        negotiation_id = ""
        if isinstance(payload, dict):
            negotiation_id = str(payload.get("id") or payload.get("negotiation_id") or "")
        return {
            "status": "submitted",
            "negotiation_id": negotiation_id or None,
            "would_send": entry,
        }
