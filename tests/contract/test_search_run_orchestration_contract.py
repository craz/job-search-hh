"""Contract checks for HH vacancy SearchRun orchestration HTTP/CLI (R2.2.4)."""

from __future__ import annotations

from pathlib import Path

from job_search_hh.cli import build_parser


def test_api_publishes_vacancies_search_path() -> None:
    api_path = Path(__file__).resolve().parents[2] / "src" / "job_search_hh" / "api.py"
    text = api_path.read_text(encoding="utf-8")
    assert "/api/v1/vacancies/search" in text
    assert "run_vacancy_search" in text
    assert "page_size" in text  # rejected as unsupported Web knob


def test_cli_exposes_vacancies_search() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "vacancies",
            "search",
            "--search-profile-id",
            "11111111-1111-1111-1111-111111111111",
            "--max-pages",
            "1",
            "--order",
            "publication_time",
        ]
    )
    assert args.command == "vacancies"
    assert args.vacancies_command == "search"
    assert args.search_profile_id == "11111111-1111-1111-1111-111111111111"
    assert args.max_pages == 1


def test_core_client_exposes_search_run_methods() -> None:
    client_path = Path(__file__).resolve().parents[2] / "src" / "job_search_hh" / "core_client.py"
    text = client_path.read_text(encoding="utf-8")
    for name in (
        "get_search_profile",
        "start_search_run",
        "add_search_run_item",
        "finalize_search_run",
        "ingest_vacancy",
        "list_search_run_items",
        "get_search_run",
    ):
        assert f"def {name}" in text
