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
    assert egress_preflight_code() is None
