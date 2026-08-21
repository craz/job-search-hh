"""Loopback-only OAuth callback listener for HH authorization codes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_search_hh.oauth import (
    OAuthError,
    OAuthSettings,
    build_authorize_url,
    exchange_authorization_code,
    token_status,
)
from job_search_hh.session import SessionPaths

ExchangeFn = Callable[..., dict[str, Any]]


@dataclass
class _CallbackState:
    expected_path: str
    expected_state: str | None
    code: str | None = None
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)


def parse_loopback_redirect(redirect_uri: str) -> tuple[str, int, str]:
    """Require a loopback http redirect URI and return bind host, port, path."""
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise OAuthError("redirect_not_http_loopback")
    host = (parsed.hostname or "").strip().casefold()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise OAuthError("redirect_not_loopback")
    port = parsed.port or 80
    path = parsed.path or "/oauth/callback"
    if not path.startswith("/"):
        path = "/" + path
    bind_host = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "::1"
    return bind_host, port, path


def _html_page(title: str, body: str) -> bytes:
    document = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body><h1>{title}</h1>"
        f"<p>{body}</p></body></html>"
    )
    return document.encode("utf-8")


def _make_handler(state: _CallbackState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != state.expected_path:
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_html_page("Not found", "Unexpected OAuth path."))
                return

            query = parse_qs(parsed.query)
            error_vals = query.get("error")
            code_vals = query.get("code")
            state_vals = query.get("state")
            error = error_vals[0] if error_vals else None
            code = code_vals[0] if code_vals else None
            returned_state = state_vals[0] if state_vals else None
            if state.expected_state and returned_state and returned_state != state.expected_state:
                state.error = "state_mismatch"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_html_page("OAuth error", "state_mismatch"))
                state.done.set()
                return
            if error:
                state.error = str(error)
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_html_page("OAuth error", str(error)))
                state.done.set()
                return
            if not code:
                state.error = "authorization_code_missing"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_html_page("OAuth error", "missing code"))
                state.done.set()
                return

            state.code = str(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                _html_page(
                    "HH OAuth OK",
                    "Authorization code received. You can close this tab.",
                )
            )
            state.done.set()

    return Handler


def oauth_acquire(
    *,
    paths: SessionPaths | None = None,
    settings: OAuthSettings | None = None,
    state: str = "job-search-hh",
    wait_seconds: float = 300.0,
    detach: bool = False,
    exchange: ExchangeFn = exchange_authorization_code,
) -> dict[str, Any]:
    """Listen on loopback redirect URI, exchange code, never return token secrets."""
    cfg = settings or OAuthSettings.from_env()
    cfg.require_client()
    bind_host, port, callback_path = parse_loopback_redirect(cfg.redirect_uri)
    authorize = build_authorize_url(cfg, state=state)

    if detach:
        child = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "job_search_hh.cli",
                "auth",
                "oauth-acquire",
                "--foreground",
                "--wait-seconds",
                str(int(wait_seconds)),
                "--state",
                state,
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                **os.environ,
                "HH_STATE_DIR": str((paths or SessionPaths.from_env()).state_dir),
                "HH_PROFILE_DIR": str((paths or SessionPaths.from_env()).profile_dir),
            },
        )
        resolved = paths or SessionPaths.from_env()
        resolved.ensure()
        (resolved.state_dir / "oauth-callback.pid").write_text(str(child.pid), encoding="utf-8")
        return {
            **authorize,
            "listening": True,
            "detached": True,
            "pid": child.pid,
            "wait_seconds": wait_seconds,
            "bind_host": bind_host,
            "bind_port": port,
            "callback_path": callback_path,
            "access_token_present": token_status(paths)["access_token_present"],
        }

    callback_state = _CallbackState(expected_path=callback_path, expected_state=state)
    handler = _make_handler(callback_state)
    try:
        server = ThreadingHTTPServer((bind_host, port), handler)
    except OSError as error:
        raise OAuthError("callback_bind_failed") from error

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        finished = callback_state.done.wait(timeout=max(1.0, wait_seconds))
        if not finished:
            raise OAuthError("callback_timeout")
        if callback_state.error:
            raise OAuthError(callback_state.error)
        if not callback_state.code:
            raise OAuthError("authorization_code_missing")
        status = exchange(callback_state.code, paths=paths, settings=cfg)
        return {
            **authorize,
            **status,
            "listening": False,
            "detached": False,
            "callback_received": True,
            "bind_host": bind_host,
            "bind_port": port,
            "callback_path": callback_path,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        # Tiny pause helps tests reuse the port quickly on some kernels.
        time.sleep(0.05)
