"""Contract checks for product-facing HH account CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_search_hh.cli import main
from job_search_hh.oauth import set_access_token
from job_search_hh.session import SessionPaths, confirm_login


def test_account_status_cli_envelope(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HH_CHROMIUM_INSTALLED", "1")
    monkeypatch.setenv("JOB_SEARCH_HH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JOB_SEARCH_HH_PROFILE_DIR", str(tmp_path / "profile"))
    paths = SessionPaths.from_env()
    confirm_login(paths, confirmed=True)
    set_access_token("cli-fixture-token", paths=paths, expires_in=3600)

    def fake_me(**_kwargs: Any) -> tuple[int | None, dict[str, Any] | None, str | None]:
        return (
            200,
            {"id": "42", "first_name": "Pat", "last_name": "Tester", "email": "pat@example.test"},
            None,
        )

    monkeypatch.setattr("job_search_hh.profile._fetch_me", fake_me)
    code = main(["account", "status"])
    captured = capsys.readouterr().out
    envelope = json.loads(captured)
    assert code == 0
    assert envelope["ok"] is True
    assert envelope["data"]["status"] == "available"
    assert envelope["data"]["account"]["external_id"] == "42"
    assert "cli-fixture-token" not in captured
    assert "access_token" not in captured
