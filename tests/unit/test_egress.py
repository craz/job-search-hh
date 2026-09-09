"""Unit tests for HH browser egress diagnostics."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from job_search_hh.egress import (
    CODE_BROWSER_PROXY_UNAVAILABLE,
    classify_browser_transport_error,
    egress_diagnostic,
    egress_preflight_code,
    is_container_local_proxy,
)


def test_is_container_local_proxy_detects_loopback() -> None:
    assert is_container_local_proxy("http://127.0.0.1:2080") is True
    assert is_container_local_proxy("http://localhost:3128") is True
    assert is_container_local_proxy("http://hh-egress:3128") is False


def test_classify_browser_transport_error_proxy_failure() -> None:
    error = RuntimeError(
        "Page.goto: net::ERR_PROXY_CONNECTION_FAILED at https://hh.ru/applicant/resumes"
    )
    assert classify_browser_transport_error(error) == CODE_BROWSER_PROXY_UNAVAILABLE


def test_classify_browser_transport_error_unknown() -> None:
    assert classify_browser_transport_error(RuntimeError("timeout")) is None


@patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:2080"}, clear=False)
def test_egress_preflight_flags_loopback_proxy() -> None:
    diag = egress_diagnostic()
    assert diag["misconfigured_loopback"] is True
    assert diag["proxy_url"] == "http://127.0.0.1:2080"
    assert egress_preflight_code() == CODE_BROWSER_PROXY_UNAVAILABLE


@patch.dict(os.environ, {"HTTP_PROXY": "http://hh-egress:3128"}, clear=False)
def test_egress_preflight_allows_supported_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "job_search_hh.egress.proxy_tcp_reachable",
        lambda _url, timeout=2.0: True,
    )
    monkeypatch.setattr(
        "job_search_hh.egress.proxy_connect_works",
        lambda _url, **_kwargs: True,
    )
    assert egress_preflight_code() is None


@patch.dict(os.environ, {"HTTP_PROXY": "http://hh-egress:3128"}, clear=False)
def test_egress_preflight_rejects_tcp_only_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """socat can listen while the host unix forwarder is dead — CONNECT must fail ready."""
    monkeypatch.setattr(
        "job_search_hh.egress.proxy_tcp_reachable",
        lambda _url, timeout=2.0: True,
    )
    monkeypatch.setattr(
        "job_search_hh.egress.proxy_connect_works",
        lambda _url, **_kwargs: False,
    )
    diag = egress_diagnostic()
    assert diag["proxy_reachable"] is True
    assert diag["proxy_connect_ok"] is False
    assert egress_preflight_code() == CODE_BROWSER_PROXY_UNAVAILABLE


def test_proxy_connect_works_parses_http_200(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSock:
        def __init__(self) -> None:
            self._sent = b""

        def settimeout(self, _value: float) -> None:
            return None

        def sendall(self, data: bytes) -> None:
            self._sent = data

        def recv(self, _n: int) -> bytes:
            return b"HTTP/1.1 200 Connection Established\r\n\r\n"

        def __enter__(self) -> FakeSock:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        "job_search_hh.egress.socket.create_connection",
        lambda *_a, **_k: FakeSock(),
    )
    from job_search_hh.egress import proxy_connect_works

    assert proxy_connect_works("http://hh-egress:3128") is True
