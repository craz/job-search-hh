"""Unit tests for gated limited apply."""

from job_search_hh.apply import limited_apply


def test_limited_apply_refuses_when_writes_disabled() -> None:
    report = limited_apply(
        [{"vacancy_id": "1", "resume_id": "r"}],
        external_writes_enabled=False,
        authorized=True,
    )
    assert report["errors"][0]["error"] == "external_writes_disabled"
    assert report["hh_write_attempted"] is False


def test_limited_apply_refuses_without_authorization_flag() -> None:
    report = limited_apply(
        [{"vacancy_id": "1", "resume_id": "r"}],
        external_writes_enabled=True,
        authorized=False,
    )
    assert report["errors"][0]["error"] == "authorization_required"


def test_limited_apply_gates_ready_without_network_write() -> None:
    report = limited_apply(
        [
            {"vacancy_id": "1", "resume_id": "r"},
            {"vacancy_id": "2", "resume_id": "r"},
        ],
        external_writes_enabled=True,
        authorized=True,
        limit=1,
    )
    assert report["execution"] == "not_implemented"
    assert report["selected"] == 1
    assert report["captcha_stop"] is True
    assert report["hh_write_attempted"] is False
