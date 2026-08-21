"""Contract tests for the versioned JSON capabilities and sync CLI surface."""

from job_search_hh.cli import build_parser, capabilities_envelope


def test_capabilities_envelope_has_stable_version_and_identity() -> None:
    """Consumers must receive schema version, component identity and safe defaults."""
    envelope = capabilities_envelope()

    assert envelope.schema_version == 1
    assert envelope.ok is True
    assert envelope.data["component"] == "job-search-hh"
    assert envelope.data["external_writes_enabled"] is False
    assert envelope.data["hh_api"] == "read-only"
    assert envelope.data["browser_automation"] in {"scaffold", "installed"}
    assert envelope.data["hh_api"] == "read-only"


def test_cli_exposes_read_only_vacancy_sync() -> None:
    """Apply stays out of the parser; vacancy sync is the only write path to Core."""
    parser = build_parser()
    args = parser.parse_args(["vacancies", "sync", "--text", "python", "--per-page", "3"])

    assert args.command == "vacancies"
    assert args.vacancies_command == "sync"
    assert args.text == "python"
    assert args.per_page == 3


def test_cli_exposes_read_only_application_sync() -> None:
    parser = build_parser()
    fixture = parser.parse_args(["applications", "sync", "--fixture", "apps.json"])
    live = parser.parse_args(["applications", "sync"])

    assert fixture.command == "applications"
    assert fixture.applications_command == "sync"
    assert str(fixture.fixture) == "apps.json"
    assert live.fixture is None


def test_cli_exposes_read_only_metrics_sync() -> None:
    parser = build_parser()
    fixture = parser.parse_args(["metrics", "sync", "--fixture", "metrics.json"])
    live = parser.parse_args(["metrics", "sync"])

    assert fixture.command == "metrics"
    assert fixture.metrics_command == "sync"
    assert str(fixture.fixture) == "metrics.json"
    assert live.fixture is None


def test_cli_exposes_apply_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["apply", "dry-run", "--fixture", "plan.json"])

    assert args.command == "apply"
    assert args.apply_command == "dry-run"
    assert str(args.fixture) == "plan.json"


def test_cli_exposes_apply_limited_with_authorization_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["apply", "limited", "--fixture", "plan.json", "--limit", "1", "--i-authorize-hh-writes"]
    )

    assert args.command == "apply"
    assert args.apply_command == "limited"
    assert args.i_authorize_hh_writes is True
    assert args.limit == 1


def test_cli_exposes_session_and_auth_status() -> None:
    parser = build_parser()
    session = parser.parse_args(["session", "status"])
    auth = parser.parse_args(["auth", "status"])

    assert session.command == "session" and session.session_command == "status"
    assert auth.command == "auth" and auth.auth_command == "status"


def test_cli_exposes_auth_open_confirm_clear() -> None:
    parser = build_parser()
    opened = parser.parse_args(["auth", "open-login", "--detach"])
    confirmed = parser.parse_args(["auth", "confirm", "--i-confirm-operator-login"])
    cleared = parser.parse_args(["auth", "clear"])

    assert opened.auth_command == "open-login" and opened.detach is True
    assert confirmed.i_confirm_operator_login is True
    assert cleared.auth_command == "clear"
