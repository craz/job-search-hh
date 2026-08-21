"""Unit tests for loopback OAuth redirect parsing and bind guards."""

from __future__ import annotations

import pytest

from job_search_hh.oauth import OAuthError
from job_search_hh.oauth_callback import parse_loopback_redirect


def test_parse_loopback_redirect_accepts_localhost() -> None:
    host, port, path = parse_loopback_redirect("http://127.0.0.1:8767/oauth/callback")
    assert host == "127.0.0.1"
    assert port == 8767
    assert path == "/oauth/callback"


def test_parse_loopback_redirect_rejects_public_host() -> None:
    with pytest.raises(OAuthError, match="redirect_not_loopback"):
        parse_loopback_redirect("http://example.com:8767/oauth/callback")


def test_parse_loopback_redirect_rejects_https() -> None:
    with pytest.raises(OAuthError, match="redirect_not_http_loopback"):
        parse_loopback_redirect("https://127.0.0.1:8767/oauth/callback")
