"""Minimal versioned HTTP boundary for product-facing HH connection status."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from job_search_hh.active_resume import set_active_resume
from job_search_hh.connection import connection_status
from job_search_hh.core_linkage import sync_active_resume_link
from job_search_hh.profile import account_profile
from job_search_hh.resume_content import read_resume_content
from job_search_hh.resume_sync import sync_resume_content
from job_search_hh.resumes import _list_resumes_raw, list_resumes
from job_search_hh.search_run_orchestration import run_vacancy_search
from job_search_hh.session import SessionError, SessionPaths, clear_login, confirm_login, open_login


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
        if parsed.path.startswith("/api/v1/resumes/") and parsed.path.endswith("/content"):
            # /api/v1/resumes/{external_id}/content — allowlist RO extract only
            parts = [p for p in parsed.path.split("/") if p]
            # ['api', 'v1', 'resumes', '{id}', 'content']
            if len(parts) == 5 and parts[3]:
                self._json(HTTPStatus.OK, read_resume_content(parts[3]))
                return
        self._json(
            HTTPStatus.NOT_FOUND,
            {"code": "not_found", "message": "Unknown path"},
        )

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "Invalid JSON body"},
            )
            return None
        if not isinstance(body, dict):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "JSON object required"},
            )
            return None
        return body

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/resumes/active":
            self._json(
                HTTPStatus.NOT_FOUND,
                {"code": "not_found", "message": "Unknown path"},
            )
            return
        body = self._read_json_body()
        if body is None:
            return
        if "external_id" not in body:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "external_id is required (string or null)"},
            )
            return
        external_id = body.get("external_id")
        if external_id is not None and not isinstance(external_id, str):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"code": "invalid_request", "message": "external_id must be a string or null"},
            )
            return
        paths = SessionPaths.from_env()
        list_report = _list_resumes_raw(
            paths,
            resumes_url="https://hh.ru/applicant/resumes",
            page_reader=None,
            timeout_seconds=45.0,
        )
        result = set_active_resume(paths, external_id, list_report=list_report)
        if not result.get("ok"):
            self._json(HTTPStatus.CONFLICT, result)
            return
        resumes = result["resumes"]
        title = None
        active = resumes.get("active_resume")
        if isinstance(active, dict):
            title = active.get("title") if isinstance(active.get("title"), str) else None
        status = None
        selection = resumes.get("selection") if isinstance(resumes.get("selection"), dict) else {}
        if selection.get("status") == "stale":
            status = "stale"
        elif external_id is None:
            status = "cleared"
        resumes["core_linkage"] = sync_active_resume_link(
            external_resume_id=external_id,
            title=title,
            status=status,
        )
        self._json(HTTPStatus.OK, resumes)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json_body()
        if body is None:
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
            if parsed.path == "/api/v1/resumes/sync":
                external_id = body.get("external_id")
                if external_id is not None and not isinstance(external_id, str):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "invalid_request",
                            "message": "external_id must be a string when provided",
                        },
                    )
                    return
                report = sync_resume_content(
                    external_resume_id=external_id if isinstance(external_id, str) else None
                )
                status = HTTPStatus.OK if report.get("ok") else HTTPStatus.CONFLICT
                self._json(status, report)
                return
            if parsed.path == "/api/v1/vacancies/search":
                profile_id = body.get("search_profile_id")
                if not isinstance(profile_id, str) or not profile_id.strip():
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "invalid_request",
                            "message": "search_profile_id is required (string)",
                        },
                    )
                    return
                execution = body.get("execution")
                if execution is not None and not isinstance(execution, dict):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "invalid_request",
                            "message": "execution must be an object when provided",
                        },
                    )
                    return
                exec_obj = execution if isinstance(execution, dict) else {}
                if "page_size" in exec_obj and exec_obj.get("page_size") is not None:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "unsupported_execution",
                            "message": (
                                "page_size is not a supported Web browser execution knob; "
                                "omit it and use max_pages/order only"
                            ),
                        },
                    )
                    return
                order = (
                    str(exec_obj.get("order") or "publication_time").strip() or "publication_time"
                )
                try:
                    max_pages = int(exec_obj.get("max_pages") or 1)
                except (TypeError, ValueError):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "invalid_request",
                            "message": "execution.max_pages must be an integer",
                        },
                    )
                    return
                max_pages = max(1, min(max_pages, 20))
                report = run_vacancy_search(
                    search_profile_id=profile_id.strip(),
                    max_pages=max_pages,
                    order=order,
                )
                status = (
                    HTTPStatus.OK
                    if str(report.get("status")) in {"success", "partial"}
                    else HTTPStatus.CONFLICT
                )
                self._json(status, report)
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
