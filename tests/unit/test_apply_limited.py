"""Unit tests for gated limited apply with live transport doubles."""

from job_search_hh.apply import limited_apply
from job_search_hh.apply_transport import RecordingLiveApplyTransport


def test_limited_apply_refuses_when_writes_disabled() -> None:
    report = limited_apply(
        [{"vacancy_id": "1", "resume_id": "r"}],
        external_writes_enabled=False,
        authorized=True,
        transport=RecordingLiveApplyTransport(),
    )
    assert report["errors"][0]["error"] == "external_writes_disabled"
    assert report["hh_write_attempted"] is False


def test_limited_apply_refuses_without_authorization_flag() -> None:
    report = limited_apply(
        [{"vacancy_id": "1", "resume_id": "r"}],
        external_writes_enabled=True,
        authorized=False,
        transport=RecordingLiveApplyTransport(),
    )
    assert report["errors"][0]["error"] == "authorization_required"


def test_limited_apply_requires_transport_when_gated() -> None:
    report = limited_apply(
        [{"vacancy_id": "1", "resume_id": "r"}],
        external_writes_enabled=True,
        authorized=True,
        transport=None,
    )
    assert report["execution"] == "refused"
    assert report["errors"][0]["error"] == "transport_required"
    assert report["hh_write_attempted"] is False


def test_limited_apply_submits_through_live_transport() -> None:
    transport = RecordingLiveApplyTransport()
    report = limited_apply(
        [
            {"vacancy_id": "1", "resume_id": "r"},
            {"vacancy_id": "2", "resume_id": "r"},
        ],
        external_writes_enabled=True,
        authorized=True,
        limit=1,
        transport=transport,
    )
    assert report["execution"] == "completed"
    assert report["selected"] == 1
    assert report["submitted"] == 1
    assert report["items"][0]["status"] == "submitted"
    assert report["captcha_stop"] is True
    assert report["hh_write_attempted"] is True
    assert len(transport.audit) == 1


def test_limited_apply_stops_on_captcha() -> None:
    transport = RecordingLiveApplyTransport(fail_with="captcha_or_auth_stop")
    report = limited_apply(
        [
            {"vacancy_id": "1", "resume_id": "r"},
            {"vacancy_id": "2", "resume_id": "r"},
        ],
        external_writes_enabled=True,
        authorized=True,
        limit=2,
        transport=transport,
    )
    assert report["execution"] == "stopped_captcha"
    assert report["submitted"] == 0
    assert report["errors"][0]["error"] == "captcha_or_auth_stop"
    assert report["hh_write_attempted"] is True
