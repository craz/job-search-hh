"""Unit tests for resume-suitable SERP URL and guard (R2.2.5)."""

from __future__ import annotations

from job_search_hh.resume_suitable import (
    map_resume_suitable_query,
    parse_source_total,
    validate_resume_suitable_page,
)


def test_map_resume_suitable_query_uses_publication_time() -> None:
    mapping = map_resume_suitable_query("abc123", page=0, order="publication_time")
    assert "resume=abc123" in mapping.url
    assert "hhtmFromLabel=vacancies_for_resume_button" in mapping.url
    assert "order_by=publication_time" in mapping.url
    assert mapping.query["page"] == "0"


def test_parse_source_total_from_suitable_heading() -> None:
    assert parse_source_total("Найдено 2 272 подходящих вакансии для резюме") == 2272
    assert parse_source_total("Найдено 50 вакансий") == 50
    assert parse_source_total(None) is None


def test_guard_accepts_matching_resume_serp() -> None:
    result = validate_resume_suitable_page(
        expected_resume_id="abc123",
        final_url=(
            "https://samara.hh.ru/search/vacancy?resume=abc123"
            "&from=resumelist&hhtmFromLabel=vacancies_for_resume_button&hhtmFrom=resume_list"
        ),
        found_text="Найдено 2 272 подходящих вакансии для резюме",
        card_count=50,
    )
    assert result["ok"] is True
    assert result["source_total"] == 2272


def test_guard_rejects_wrong_resume_or_generic_serp() -> None:
    wrong = validate_resume_suitable_page(
        expected_resume_id="abc123",
        final_url="https://hh.ru/search/vacancy?resume=other&text=python",
        found_text="Найдено 2 272 подходящих вакансии для резюме",
        card_count=50,
    )
    assert wrong["ok"] is False
    assert wrong["code"] == "resume_search_page_mismatch"

    generic = validate_resume_suitable_page(
        expected_resume_id="abc123",
        final_url="https://hh.ru/search/vacancy?resume=abc123&text=python",
        found_text="Найдено 3686 вакансий «python»",
        card_count=50,
    )
    assert generic["ok"] is False
    assert generic["code"] == "resume_search_page_mismatch"
