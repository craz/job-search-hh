"""Minimal versioned HTTP boundary for product-facing HH connection status."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from job_search_hh.connection import connection_status
from job_search_hh.profile import account_profile
from job_search_hh.resumes import list_resumes
from job_search_hh.session import SessionError, clear_login, confirm_login, open_login


def _secret_leak(payload: dict[str, Any]) -> bool:
    blob = json.dumps(payload, ensure_ascii=False)
    return any(
        marker in blob
        for marker in ('"access_token":', '"refresh_token":', '"client_secret":', '"cookie":')
    )


class ApiHandler(BaseHTTPRequestHandler):
    """Serve connection status and safe login actions; never dump secrets."""

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        if _secret_leak(payload):
            payload = {"code": "token_leak_blocked", "message": "Refused to emit secrets"}
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health/ready":
            self._json(HTTPStatus.OK, {"status": "ok", "component": "job-search-hh"})
            return
        if parsed.path == "/api/v1/connection":
            self._json(HTTPStatus.OK, connection_status())
            return
        if parsed.path == "/api/v1/account":
            self._json(HTTPStatus.OK, account_profile())
            return
        if parsed.path == "/api/v1/resumes":
            self._json(HTTPStatus.OK, list_resumes())
            return
        self._json(
            HTTPStatus.NOT_FOUND,
            {"code": "not_found", "message": "Unknown path"},
        )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "Invalid JSON body"},
            )
            return
        if not isinstance(body, dict):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "JSON object required"},
            )
            return

        try:
            if parsed.path == "/api/v1/connection/open-login":
                report = open_login(detach=True)
                report["connection"] = connection_status()
                self._json(HTTPStatus.OK, report)
                return
            if parsed.path == "/api/v1/connection/confirm":
                if not bool(body.get("confirmed")):
                    raise SessionError("confirmation_required")
                report = confirm_login(confirmed=True)
                report["connection"] = connection_status()
                self._json(HTTPStatus.OK, report)
                return
            if parsed.path == "/api/v1/connection/clear":
                report = clear_login()
                report["connection"] = connection_status()
                self._json(HTTPStatus.OK, report)
                return
        except SessionError as error:
            self._json(
                HTTPStatus.CONFLICT,
                {"code": str(error), "message": str(error), "connection": connection_status()},
            )
            return

        self._json(
            HTTPStatus.NOT_FOUND,
            {"code": "not_found", "message": "Unknown path"},
        )

    def log_message(self, format: str, *args: object) -> None:
        """Keep routine local requests out of operator stdout noise."""


def main() -> None:
    """Run the internal Compose HTTP service for connection status."""
    port = int(os.getenv("HH_API_PORT", os.getenv("JOB_SEARCH_HH_API_PORT", "8092")))
    ThreadingHTTPServer(("0.0.0.0", port), ApiHandler).serve_forever()


if __name__ == "__main__":
    main()
