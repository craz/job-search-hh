"""Unit tests for HH vacancy and application normalization."""

from job_search_hh.normalize import (
    application_idempotency_key,
    idempotency_key,
    metric_idempotency_key,
    normalize_application,
    normalize_metric,
    normalize_vacancy,
    vacancy_detail_to_ingest,
)


def test_normalize_maps_hh_search_item_to_core_payload() -> None:
    payload = normalize_vacancy(
        {
            "id": "42",
            "name": "Python Developer",
            "alternate_url": "https://hh.ru/vacancy/42",
            "employer": {"id": "7", "name": "Acme"},
            "snippet": {"requirement": "Python 3", "responsibility": "APIs"},
        }
    )

    assert payload == {
        "company_name": "Acme",
        "company_external_id": "7",
        "source": "hh",
        "external_id": "42",
        "title": "Python Developer",
        "url": "https://hh.ru/vacancy/42",
        "description": "Python 3\nAPIs",
    }
    assert idempotency_key("42") == "hh:vacancy:42"


def test_normalize_falls_back_to_company_name_identity() -> None:
    payload = normalize_vacancy(
        {
            "id": "9",
            "name": "SRE",
            "alternate_url": "https://hh.ru/vacancy/9",
            "employer": {"name": "Solo Co"},
        }
    )

    assert payload["company_external_id"] == "name:solo co"
    assert "description" not in payload


def test_normalize_application_maps_negotiation_state() -> None:
    payload = normalize_application(
        {
            "id": "neg-9",
            "created_at": "2026-08-20T12:00:00+00:00",
            "state": "interview",
        },
        vacancy_id="11111111-1111-1111-1111-111111111111",
    )

    assert payload == {
        "vacancy_id": "11111111-1111-1111-1111-111111111111",
        "source": "hh",
        "external_id": "neg-9",
        "applied_at": "2026-08-20T12:00:00+00:00",
        "result": "interview",
    }
    assert application_idempotency_key("neg-9") == "hh:application:neg-9"


def test_normalize_metric_maps_daily_snapshot() -> None:
    metric_date, payload = normalize_metric(
        {
            "metric_date": "2026-08-20",
            "views_total": 10,
            "applications": 2,
            "notes": "day",
        }
    )

    assert metric_date == "2026-08-20"
    assert payload == {"views_total": 10, "applications": 2, "notes": "day"}
    assert metric_idempotency_key(metric_date, payload).startswith("hh:metric:2026-08-20:")


def test_vacancy_detail_to_ingest_maps_hh_dto_fields() -> None:
    payload = vacancy_detail_to_ingest(
        {
            "external_id": "136706048",
            "title": "Senior Python Developer",
            "url": "https://samara.hh.ru/vacancy/136706048?x=1",
            "employer_id": "777",
            "employer_name": "Okkam",
            "description": "Full description for scoring.",
            "area_text": "Москва",
            "experience_text": "3–6 лет",
            "employment_text": "Полная занятость",
            "schedule_text": "График: 5/2",
            "work_format_text": "Формат работы: удалённо",
            "archived": False,
        }
    )
    assert payload["source"] == "hh"
    assert payload["external_id"] == "136706048"
    assert payload["company_external_id"] == "777"
    assert payload["company_name"] == "Okkam"
    assert payload["description"].startswith("Full description")
    assert payload["archived"] is False
    assert "salary_text" not in payload


def test_vacancy_detail_falls_back_to_name_identity_when_employer_id_missing() -> None:
    payload = vacancy_detail_to_ingest(
        {
            "external_id": "9",
            "title": "SRE",
            "url": "https://hh.ru/vacancy/9",
            "employer_name": "Solo Co",
        }
    )
    assert payload["company_external_id"] == "name:solo co"
