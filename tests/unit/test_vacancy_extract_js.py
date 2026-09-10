"""Guard DETAIL_EXTRACT_JS / SEARCH_EXTRACT_JS against regressing SyntaxErrors."""

from __future__ import annotations

import re

import pytest

from job_search_hh.vacancy_browser import _detail_failure_code
from job_search_hh.vacancy_extractors import DETAIL_EXTRACT_JS, SEARCH_EXTRACT_JS


def _top_level_const_href_count(js_source: str) -> int:
    """Count `const href` declarations outside nested blocks (approx via indent)."""
    body = js_source
    if body.startswith("() =>"):
        body = body.split("{", 1)[1].rsplit("}", 1)[0]
    count = 0
    for line in body.splitlines():
        if re.match(r"^[ \t]*const href\b", line):
            # Nested for-loop / block consts are indented deeper than 2 spaces of function body
            # Function body statements in our templates use 2-space indent.
            indent = len(line) - len(line.lstrip(" "))
            if indent <= 2:
                count += 1
    return count


def test_detail_extract_js_declares_href_once() -> None:
    assert _top_level_const_href_count(DETAIL_EXTRACT_JS) == 1
    # Hard guard: the historical double-declare bug was exactly this second line.
    assert "const href = location.href || ''" not in DETAIL_EXTRACT_JS


def test_search_extract_js_top_level_href_once() -> None:
    assert _top_level_const_href_count(SEARCH_EXTRACT_JS) == 1


def test_detail_failure_code_distinguishes_extract_from_network() -> None:
    class _Err(Exception):
        pass

    extract = _Err("Page.evaluate: SyntaxError: Identifier 'href' has already been declared")
    assert _detail_failure_code(extract) == "page_extract_failed"

    proxy = _Err("net::ERR_PROXY_CONNECTION_FAILED at https://hh.ru/vacancy/1")
    assert _detail_failure_code(proxy) == "browser_proxy_unavailable"

    tunnel = _Err("Proxy CONNECT aborted")
    assert _detail_failure_code(tunnel) == "browser_proxy_unavailable"

    other = _Err("net::ERR_CONNECTION_RESET")
    assert _detail_failure_code(other) == "vacancy_detail_failed"


def test_detail_extract_js_evaluates_in_playwright() -> None:
    """Fixture HTML must accept DETAIL_EXTRACT_JS without SyntaxError."""
    pytest.importorskip("playwright.sync_api")
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from threading import Thread

    from playwright.sync_api import sync_playwright

    from job_search_hh.vacancy_extractors import extract_detail_page, normalize_detail_payload

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, directory=str(fixtures), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/vacancy/"):
                self.path = "/vacancy_detail.html"
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    detail_url = f"http://127.0.0.1:{port}/vacancy/1001"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(detail_url)
            raw = extract_detail_page(page)
            detail = normalize_detail_payload(raw if isinstance(raw, dict) else {})
            browser.close()
    except Exception as error:  # pragma: no cover
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message:
            pytest.skip(f"playwright chromium unavailable: {message}")
        raise
    finally:
        server.shutdown()
        server.server_close()
    assert detail["kind"] == "ok"
    assert detail["content"]["external_id"] == "1001"
