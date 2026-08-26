"""Contract checks for HH resume list HTTP surface (R1.3)."""

from __future__ import annotations

from pathlib import Path


def test_api_publishes_resumes_path() -> None:
    api_path = Path(__file__).resolve().parents[2] / "src" / "job_search_hh" / "api.py"
    text = api_path.read_text(encoding="utf-8")
    assert "/api/v1/resumes" in text
    assert "list_resumes" in text
    assert "/api/v1/resumes/active" in text
    assert "set_active_resume" in text
