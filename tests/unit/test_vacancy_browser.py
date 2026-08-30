"""Unit tests for HH browser RO vacancy acquisition (R2.2.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_search_hh.session import ProfileLock, SessionPaths, confirm_login
from job_search_hh.vacancy_browser import (
    STATUS_ACTION_REQUIRED,
    STATUS_AVAILABLE,
    STATUS_NOT_AUTHORIZED,
    STATUS_PARTIAL,
    STATUS_PERMISSION_BLOCKED,
    STATUS_UNAVAILABLE,
    acquire_vacancies,
)
from job_search_hh.vacancy_dto import DETAIL_ALLOWLIST, SUMMARY_ALLOWLIST, allowlist_detail
from job_search_hh.vacancy_extractors import (
    EXTRACTOR_VERSION,
    canonicalize_vacancy_url,
    extract_detail_page,
    extract_search_page,
    normalize_detail_payload,
    normalize_search_payload,
)
from job_search_hh.vacancy_query import (
    ExecutionPolicy,
    SearchCriteria,
    criteria_from_mapping,
    map_search_query,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _paths(tmp_path: Path) -> SessionPaths:
    return SessionPaths(state_dir=tmp_path / "state", profile_dir=tmp_path / "profile")


def test_search_criteria_map_to_verified_web_params() -> None:
    mapped = map_search_query(
        SearchCriteria(
            text="python",
            area=1,
            salary=200000,
            experience="between3And6",
            employment="full",
            schedule="remote",
            search_field="name",
            only_with_salary=True,
        ),
        ExecutionPolicy(order="publication_time", max_pages=2),
        page=1,
    )
    assert mapped.query["text"] == "python"
    assert mapped.query["area"] == "1"
    assert mapped.query["salary"] == "200000"
    assert mapped.query["experience"] == "between3And6"
    assert mapped.query["employment"] == "full"
    assert mapped.query["schedule"] == "remote"
    assert mapped.query["search_field"] == "name"
    assert mapped.query["only_with_salary"] == "true"
    assert mapped.query["order_by"] == "publication_time"
    assert mapped.query["page"] == "1"
    assert mapped.unsupported == []
    assert "search/vacancy?" in mapped.url


def test_unknown_criterion_and_page_size_are_reported() -> None:
    mapped = map_search_query(
        criteria_from_mapping({"text": "python", "foo_filter": "x"}),
        ExecutionPolicy(order="publication_time", max_pages=1, page_size=20),
    )
    reasons = {item["field"]: item["reason"] for item in mapped.unsupported}
    assert reasons["foo_filter"] == "criterion_not_mapped_to_hh_web_search"
    assert reasons["page_size"] == "execution_page_size_not_supported_on_hh_web"
    assert mapped.page_size_note


def test_normalize_search_dedupes_and_allowlists() -> None:
    payload = {
        "kind": "ok",
        "items": [
            {
                "external_id": "1001",
                "title": "A",
                "url": "/vacancy/1001",
                "employer_name": "Acme",
                "noise": "drop-me",
            },
            {
                "external_id": "1001",
                "title": "dup",
                "url": "/vacancy/1001",
            },
            {"external_id": "1002", "title": "B", "url": "https://x.hh.ru/vacancy/1002"},
        ],
        "meta": {"found_text": "Найдено 2", "pager_labels": ["1", "2"]},
    }
    normalized = normalize_search_payload(payload, page=0, source_url="https://hh.ru/search")
    assert normalized["kind"] == "ok"
    assert [i["external_id"] for i in normalized["items"]] == ["1001", "1002"]
    assert normalized["items"][0]["url"] == "https://hh.ru/vacancy/1001"
    assert "noise" not in normalized["items"][0]
    assert set(normalized["items"][0]).issubset(SUMMARY_ALLOWLIST)


def test_normalize_detail_allowlist_and_missing_optional() -> None:
    normalized = normalize_detail_payload(
        {
            "kind": "ok",
            "content": {
                "external_id": "1001",
                "title": "Python",
                "url": "https://hh.ru/vacancy/1001",
                "description": "Full text",
                "employer_name": "Acme",
                "secret_dom": "<html/>",
            },
        }
    )
    assert normalized["kind"] == "ok"
    content = normalized["content"]
    assert content is not None
    assert content["description"] == "Full text"
    assert "secret_dom" not in content
    assert "salary_text" not in content
    assert set(content).issubset(DETAIL_ALLOWLIST)


def test_canonicalize_vacancy_url() -> None:
    assert (
        canonicalize_vacancy_url("https://samara.hh.ru/vacancy/136706048?query=python")
        == "https://hh.ru/vacancy/136706048"
    )


def test_acquire_without_login_skips_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    called = {"n": 0}

    def boom(**_kwargs: Any) -> dict[str, Any]:
        called["n"] += 1
        return {"kind": "ok", "pages": [], "details": []}

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=1),
        paths=_paths(tmp_path),
        page_reader=boom,
    )
    assert report["status"] == STATUS_NOT_AUTHORIZED
    assert report["code"] == "browser_login_required"
    assert report["recovery"]["kind"] == "reauth"
    assert report["hh_writes"] is False
    assert report["core_ingestion"] is False
    assert called["n"] == 0


def test_profile_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    ProfileLock(paths.profile_dir).acquire("login-browser")

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("must not run")

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        paths=paths,
        page_reader=boom,
    )
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "profile_locked"


def test_captcha_is_action_required_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def captcha(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "captcha_or_action_required", "pages": [], "details": []}

    report = acquire_vacancies(SearchCriteria(text="python"), paths=paths, page_reader=captcha)
    assert report["status"] == STATUS_ACTION_REQUIRED
    assert report["summaries"] == []
    assert report["recovery"]["kind"] == "captcha_or_action_required"


def test_permission_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def blocked(**_kwargs: Any) -> dict[str, Any]:
        return {"kind": "permission_blocked", "pages": [], "details": []}

    report = acquire_vacancies(SearchCriteria(text="python"), paths=paths, page_reader=blocked)
    assert report["status"] == STATUS_PERMISSION_BLOCKED
    assert report["code"] == "browser_vacancy_forbidden"


def test_acquire_ok_pagination_and_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)
    fixture = json_load(FIXTURES / "vacancy_acquire_ok.json")

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return fixture

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=2, page_size=20),
        paths=paths,
        page_reader=reader,
        fetch_details=True,
        detail_limit=1,
    )
    assert report["status"] == STATUS_AVAILABLE
    assert report["transport"] == "browser_readonly"
    assert report["extractor_version"] == EXTRACTOR_VERSION
    assert len(report["summaries"]) == 2
    assert report["pagination"]["pages_fetched"] == 2
    assert report["pagination"]["max_pages_reached"] is True
    assert report["details"][0]["content"]["description"].startswith("Полное описание")
    assert any(item["field"] == "page_size" for item in report["unsupported_mapping"])
    assert report["hh_writes"] is False
    assert report["core_ingestion"] is False


def test_partial_page_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "pages": [
                {
                    "page": 0,
                    "status": "ok",
                    "code": "ready",
                    "items": [
                        {
                            "external_id": "1",
                            "title": "A",
                            "url": "https://hh.ru/vacancy/1",
                        }
                    ],
                    "meta": {"observed_page_size": 1},
                },
                {
                    "page": 1,
                    "status": "failed",
                    "code": "search_page_failed",
                    "items": [],
                    "meta": {},
                },
            ],
            "details": [],
        }

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        ExecutionPolicy(max_pages=2),
        paths=paths,
        page_reader=reader,
        fetch_details=False,
    )
    assert report["status"] == STATUS_PARTIAL
    assert report["code"] == "partial_pagination"
    assert report["pagination"]["partial"] is True
    assert len(report["summaries"]) == 1


def test_malformed_search_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    paths = _paths(tmp_path)
    confirm_login(paths, confirmed=True)

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "ok",
            "pages": [
                {
                    "page": 0,
                    "status": "failed",
                    "code": "page_parse_failed",
                    "items": [],
                    "meta": {},
                }
            ],
            "details": [],
        }

    report = acquire_vacancies(
        SearchCriteria(text="python"),
        paths=paths,
        page_reader=reader,
        fetch_details=False,
    )
    assert report["status"] == STATUS_UNAVAILABLE
    assert report["code"] == "search_page_failed"
    assert report["summaries"] == []


def test_html_fixtures_extract_with_playwright() -> None:
    """Exercise real Playwright extractors against HTML fixtures over http://.

    file:// pages have a null origin; History API and realistic /vacancy/<id>
    URLs are unreliable there. Serve fixtures from a loopback HTTP server so the
    extractor reads location.href under a normal browser origin.
    """
    pytest.importorskip("playwright.sync_api")
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from playwright.sync_api import sync_playwright
    from threading import Thread

    class _FixtureHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(FIXTURES), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/vacancy/"):
                self.path = "/vacancy_detail.html"
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    search_url = f"{base}/vacancy_search_serp.html"
    detail_url = f"{base}/vacancy/1001"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(search_url)
            raw = extract_search_page(page)
            normalized = normalize_search_payload(raw, page=0, source_url=search_url)
            assert [i["external_id"] for i in normalized["items"]] == ["1001", "1002"]
            assert normalized["items"][0]["employer_name"] == "Acme LLC"
            assert normalized["items"][0]["salary_text"]

            page.goto(detail_url)
            detail_raw = extract_detail_page(page)
            detail = normalize_detail_payload(detail_raw)
            assert detail["kind"] == "ok"
            assert detail["content"]["external_id"] == "1001"
            assert "scoring" in (detail["content"].get("description") or "")
            browser.close()
    except Exception as error:  # pragma: no cover - host without browser binaries
        message = str(error)
        if "Executable doesn't exist" in message or "playwright install" in message:
            pytest.skip(f"playwright chromium unavailable: {message}")
        raise
    finally:
        server.shutdown()
        server.server_close()


def test_allowlist_detail_rejects_raw_dom() -> None:
    cleaned = allowlist_detail(
        {"external_id": "1", "title": "T", "description": "D", "raw_html": "<b>x</b>"}
    )
    assert "raw_html" not in cleaned


def json_load(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload
