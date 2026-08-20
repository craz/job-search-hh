"""Unit tests for HH vacancy and application normalization."""

from job_search_hh.normalize import (
    application_idempotency_key,
    idempotency_key,
    normalize_application,
    normalize_vacancy,
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
