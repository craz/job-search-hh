"""Executable pytest-bdd bindings for OAuth token storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pytest_bdd import given, scenarios, then, when

from job_search_hh.oauth import set_access_token, token_status

scenarios("../features/oauth_token_store.feature")


@given("пустой HH state для token", target_fixture="token_paths")
def empty_token_state(tmp_path: Path, monkeypatch: Any) -> Path:
    state = tmp_path / "state"
    profile = tmp_path / "profile"
    state.mkdir()
    profile.mkdir()
    monkeypatch.setenv("HH_STATE_DIR", str(state))
    monkeypatch.setenv("HH_PROFILE_DIR", str(profile))
    monkeypatch.delenv("JOB_SEARCH_HH_ACCESS_TOKEN", raising=False)
    return state


@when("оператор сохраняет access token из файла", target_fixture="set_token_report")
def store_token_from_file(token_paths: Path, tmp_path: Path) -> dict[str, Any]:
    token_file = tmp_path / "secret.token"
    token_file.write_text("super-secret-access-token\n", encoding="utf-8")
    return set_access_token(token_file.read_text(encoding="utf-8"))


@then("token-status показывает access_token_present")
def token_present(set_token_report: dict[str, Any], token_paths: Path) -> None:
    del token_paths
    assert set_token_report["access_token_present"] is True
    assert token_status()["access_token_present"] is True
    assert set_token_report["source"] == "token_file"


@then("JSON ответа не содержит сырой access_token")
def no_raw_token(set_token_report: dict[str, Any]) -> None:
    dumped = json.dumps(set_token_report, ensure_ascii=False, sort_keys=True)
    assert '"access_token":' not in dumped
    assert "super-secret-access-token" not in dumped
