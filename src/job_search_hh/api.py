"""Minimal versioned HTTP boundary for product-facing HH connection status."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from job_search_hh.active_resume import set_active_resume
from job_search_hh.challenge_handoff import (
    confirm_challenge_cleared,
    open_challenge_browser,
    public_challenge_view,
    read_challenge_screenshot_bytes,
)
from job_search_hh.connection import connection_status
from job_search_hh.core_linkage import sync_active_resume_link
from job_search_hh.egress import egress_diagnostic, egress_preflight_code
from job_search_hh.profile import account_profile
from job_search_hh.recovery import with_recovery
from job_search_hh.resume_content import read_resume_content
from job_search_hh.resume_sync import sync_resume_content
from job_search_hh.resumes import _list_resumes_raw, list_resumes
from job_search_hh.search_run_orchestration import run_resume_suitable_search, run_vacancy_search
from job_search_hh.session import SessionError, SessionPaths, clear_login, confirm_login, open_login
from job_search_hh.vacancy_content_refresh import refresh_vacancy_content
from job_search_hh.vacancy_source_status import check_vacancy_source_status


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
            from job_search_hh.session import read_auth_session

            egress = egress_diagnostic()
            preflight_code = egress_preflight_code()
            auth_session = read_auth_session(SessionPaths.from_env())
            browser_egress = "unavailable" if preflight_code else "ok"
            payload = {
                "status": "ok" if not preflight_code else "degraded",
                "component": "job-search-hh",
                "api": "ok",
                "browser_egress": browser_egress,
                "auth_session": auth_session,
                "egress": egress,
            }
            if preflight_code:
                payload.update(
                    {
                        "code": preflight_code,
                        "message": (
                            "Local HH browser egress is unavailable; "
                            "restore the full stack with make boot or make up."
                        ),
                    }
                )
            status = HTTPStatus.OK if not preflight_code else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(status, with_recovery(payload))
            return
        if parsed.path == "/api/v1/connection":
            payload = connection_status()
            challenge = public_challenge_view()
            if challenge:
                payload = dict(payload)
                payload["challenge"] = challenge
            self._json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/v1/challenge":
            challenge = public_challenge_view()
            if not challenge:
                self._json(HTTPStatus.OK, {"active": False, "challenge": None})
                return
            self._json(HTTPStatus.OK, {"active": True, "challenge": challenge})
            return
        if parsed.path == "/api/v1/challenge/screenshot":
            shot = read_challenge_screenshot_bytes()
            if shot is None:
                self._json(
                    HTTPStatus.NOT_FOUND,
                    {"code": "screenshot_unavailable", "message": "No challenge screenshot"},
                )
                return
            content, filename = shot
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
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
        if parsed.path.startswith("/api/v1/vacancies/") and parsed.path.endswith("/source-status"):
            # /api/v1/vacancies/{external_id}/source-status — RO archive/active check
            parts = [p for p in parsed.path.split("/") if p]
            # ['api', 'v1', 'vacancies', '{id}', 'source-status']
            if len(parts) == 5 and parts[3]:
                self._json(HTTPStatus.OK, check_vacancy_source_status(parts[3]))
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
            if parsed.path == "/api/v1/connection/open-challenge":
                body_url = body.get("challenge_url")
                url = body_url if isinstance(body_url, str) else None
                report = open_challenge_browser(challenge_url=url, detach=True)
                report["connection"] = connection_status()
                self._json(HTTPStatus.OK, report)
                return
            if parsed.path == "/api/v1/connection/confirm-challenge":
                report = confirm_challenge_cleared()
                report["connection"] = connection_status()
                status = HTTPStatus.OK if report.get("ok") else HTTPStatus.CONFLICT
                self._json(status, report)
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
            parts = [p for p in parsed.path.split("/") if p]
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "v1"
                and parts[2] == "vacancies"
                and parts[4] == "refresh-content"
                and parts[3]
            ):
                report = refresh_vacancy_content(parts[3])
                status = (
                    HTTPStatus.OK
                    if report.get("ok")
                    else (
                        HTTPStatus.CONFLICT
                        if str(report.get("code") or "") not in {"invalid_vacancy_id"}
                        else HTTPStatus.BAD_REQUEST
                    )
                )
                self._json(status, report)
                return
            if parsed.path == "/api/v1/vacancies/suitable":
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
                            "message": "page_size is not supported for browser acquisition",
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
                try:
                    start_page = int(exec_obj.get("start_page") or 0)
                except (TypeError, ValueError):
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "code": "invalid_request",
                            "message": "execution.start_page must be an integer",
                        },
                    )
                    return
                report = run_resume_suitable_search(
                    max_pages=max(1, min(max_pages, 20)),
                    start_page=max(0, min(start_page, 39)),
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
                {
                    "code": str(error),
                    "message": str(error),
                    "connection": connection_status(),
                    "browser_started": False,
                    "interactive_ready": False,
                    "ok": False,
                },
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
    import logging

    from job_search_hh.challenge_handoff import CAPTURE_IMPL_ID

    logging.getLogger("job_search_hh").info("hh_api_start capture_impl=%s", CAPTURE_IMPL_ID)
    port = int(os.getenv("HH_API_PORT", os.getenv("JOB_SEARCH_HH_API_PORT", "8092")))
    ThreadingHTTPServer(("0.0.0.0", port), ApiHandler).serve_forever()


if __name__ == "__main__":
    main()
