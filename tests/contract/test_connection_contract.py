"""Contract checks for product-facing HH connection CLI."""

from __future__ import annotations

import json
from pathlib import Path

from job_search_hh.cli import main
from job_search_hh.oauth import set_access_token
from job_search_hh.session import SessionPaths, confirm_login


def test_connection_status_cli_envelope(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setenv("JOB_SEARCH_HH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JOB_SEARCH_HH_PROFILE_DIR", str(tmp_path / "profile"))
    paths = SessionPaths.from_env()
    confirm_login(paths, confirmed=True)
    set_access_token("cli-fixture-token", paths=paths, expires_in=3600)

    code = main(["connection", "status"])
    captured = capsys.readouterr().out
    envelope = json.loads(captured)
    assert code == 0
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    assert envelope["data"]["status"] == "connected"
    assert "cli-fixture-token" not in captured
    assert "access_token" not in captured
