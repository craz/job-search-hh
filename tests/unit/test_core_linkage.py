"""Unit tests for Core HH resume linkage sync helper."""

from __future__ import annotations

from typing import Any

from job_search_hh.core_client import CoreError
from job_search_hh.core_linkage import sync_active_resume_link


class _FakeCore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def put_hh_resume_link(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise CoreError("core_down")
        return {
            "candidate_profile": {"id": "00000000-0000-0000-0000-000000000001"},
            "profile_version": {
                "id": "00000000-0000-0000-0000-000000000002",
                "label": "r1-default",
            },
            "hh_resume_link": {
                "source": "hh",
                "external_resume_id": kwargs.get("external_resume_id"),
                "status": "active" if kwargs.get("external_resume_id") else "cleared",
            },
        }


def test_sync_active_resume_link_ok() -> None:
    core = _FakeCore()
    report = sync_active_resume_link(
        external_resume_id="resumehash01",
        title="PM",
        core=core,  # type: ignore[arg-type]
    )
    assert report["ok"] is True
    assert report["candidate_context"]["hh_resume_link"]["external_resume_id"] == "resumehash01"
    assert core.calls[0]["external_resume_id"] == "resumehash01"


def test_sync_active_resume_link_core_failure_is_soft() -> None:
    report = sync_active_resume_link(
        external_resume_id="resumehash01",
        core=_FakeCore(fail=True),  # type: ignore[arg-type]
    )
    assert report["ok"] is False
    assert report["code"] == "core_linkage_unavailable"
