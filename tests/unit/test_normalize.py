"""Unit tests for HH vacancy normalization."""

from job_search_hh.normalize import idempotency_key, normalize_vacancy


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
