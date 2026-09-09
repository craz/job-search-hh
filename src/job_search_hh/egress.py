"""Local browser egress / HTTP proxy diagnostics for the HH container."""

from __future__ import annotations

import os
import socket
from typing import Any
from urllib.parse import urlparse

CODE_BROWSER_PROXY_UNAVAILABLE = "browser_proxy_unavailable"

# CONNECT target used only to prove the proxy path works (not a product dependency).
_CONNECT_PROBE_HOST = "hh.ru"
_CONNECT_PROBE_PORT = 443


def _proxy_env_candidates() -> list[str]:
    urls: list[str] = []
    for key in ("HH_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.getenv(key) or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def effective_proxy_url() -> str | None:
    candidates = _proxy_env_candidates()
    return candidates[0] if candidates else None


def _is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def is_container_local_proxy(url: str) -> bool:
    """True when the proxy URL points at loopback inside the container."""
    parsed = urlparse(url)
    return _is_loopback_host(parsed.hostname or "")


def proxy_tcp_reachable(url: str, *, timeout: float = 2.0) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def proxy_connect_works(
    url: str,
    *,
    dest_host: str = _CONNECT_PROBE_HOST,
    dest_port: int = _CONNECT_PROBE_PORT,
    timeout: float = 4.0,
) -> bool:
    """True when the HTTP proxy accepts CONNECT end-to-end (not merely TCP listen).

    ``hh-egress`` socat can stay up while the host unix-socket forwarder is dead;
    TCP to :3128 then succeeds but CONNECT aborts. Browser automation needs CONNECT.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            request = (
                f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\nHost: {dest_host}:{dest_port}\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            response = b""
            while b"\r\n" not in response and len(response) < 512:
                chunk = sock.recv(256)
                if not chunk:
                    break
                response += chunk
    except OSError:
        return False
    status_line = response.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
    # HTTP proxies return "HTTP/1.x 200 ..." on successful CONNECT.
    parts = status_line.split()
    return len(parts) >= 2 and parts[1] == "200"


def classify_browser_transport_error(error: BaseException) -> str | None:
    message = str(error)
    if "ERR_PROXY_CONNECTION_FAILED" in message:
        return CODE_BROWSER_PROXY_UNAVAILABLE
    if "Proxy CONNECT aborted" in message:
        return CODE_BROWSER_PROXY_UNAVAILABLE
    return None


def egress_diagnostic() -> dict[str, Any]:
    proxy = effective_proxy_url()
    diag: dict[str, Any] = {
        "proxy_url": proxy,
        "misconfigured_loopback": False,
        "proxy_reachable": None,
        "proxy_connect_ok": None,
    }
    if not proxy:
        diag["proxy_reachable"] = True
        diag["proxy_connect_ok"] = True
        return diag
    if is_container_local_proxy(proxy):
        diag["misconfigured_loopback"] = True
        diag["proxy_reachable"] = False
        diag["proxy_connect_ok"] = False
        return diag
    tcp_ok = proxy_tcp_reachable(proxy)
    diag["proxy_reachable"] = tcp_ok
    if not tcp_ok:
        diag["proxy_connect_ok"] = False
        return diag
    diag["proxy_connect_ok"] = proxy_connect_works(proxy)
    return diag


def egress_preflight_code() -> str | None:
    diag = egress_diagnostic()
    if diag.get("misconfigured_loopback"):
        return CODE_BROWSER_PROXY_UNAVAILABLE
    if diag.get("proxy_reachable") is False:
        return CODE_BROWSER_PROXY_UNAVAILABLE
    if diag.get("proxy_connect_ok") is False:
        return CODE_BROWSER_PROXY_UNAVAILABLE
    return None
