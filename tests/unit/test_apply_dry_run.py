"""Unit tests for apply dry-run planning."""

from pathlib import Path

from job_search_hh.apply import ApplyError, dry_run_apply, load_apply_plan
from job_search_hh.apply_transport import ApplyTransportError, FakeApplyTransport


def test_dry_run_records_audit_without_live_flag() -> None:
    transport = FakeApplyTransport()
    report = dry_run_apply(
        [{"vacancy_id": "42", "resume_id": "r1", "message": "hello"}],
        transport,
    )

    assert report["hh_write_attempted"] is False
    assert report["items"][0]["would_send"]["message_chars"] == 5
    assert transport.audit[0]["body_keys"] == ["message", "resume_id", "vacancy_id"]


def test_fake_transport_rejects_live_intent() -> None:
    transport = FakeApplyTransport()
    try:
        transport.submit({"live": True, "body": {}})
    except ApplyTransportError as error:
        assert str(error) == "live_apply_forbidden"
    else:  # pragma: no cover
        raise AssertionError("expected live apply to fail")
    assert transport.write_attempted is True


def test_incomplete_plan_is_reported() -> None:
    report = dry_run_apply([{"vacancy_id": "42"}])
    assert report["simulated"] == 0
    assert report["errors"][0]["error"] == "incomplete_apply_plan_item"


def test_empty_plan_rejected_on_load(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text('{"items": []}', encoding="utf-8")
    try:
        load_apply_plan(path)
    except ApplyError as error:
        assert str(error) == "invalid_apply_plan"
    else:  # pragma: no cover
        raise AssertionError("expected empty plan to fail")
