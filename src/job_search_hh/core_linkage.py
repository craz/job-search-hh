"""Sync HH active resume selection to Core CandidateProfile linkage (R1.5)."""

from __future__ import annotations

from typing import Any

from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient, CoreError


def sync_active_resume_link(
    *,
    external_resume_id: str | None,
    title: str | None = None,
    status: str | None = None,
    core: CoreClient | None = None,
) -> dict[str, Any]:
    """Best-effort Core linkage update; never raises into product select path."""
    client = core or CoreClient(Settings.from_env().core_url)
    try:
        context = client.put_hh_resume_link(
            external_resume_id=external_resume_id,
            title=title,
            status=status,
        )
        return {"ok": True, "code": "synced", "candidate_context": context}
    except CoreError as error:
        return {
            "ok": False,
            "code": "core_linkage_unavailable",
            "message": str(error)[:200],
        }
