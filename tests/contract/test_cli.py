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
    args = parser.parse_args(["applications", "sync", "--fixture", "apps.json"])

    assert args.command == "applications"
    assert args.applications_command == "sync"
    assert str(args.fixture) == "apps.json"


def test_cli_exposes_read_only_metrics_sync() -> None:
    parser = build_parser()
    args = parser.parse_args(["metrics", "sync", "--fixture", "metrics.json"])

    assert args.command == "metrics"
    assert args.metrics_command == "sync"
    assert str(args.fixture) == "metrics.json"


def test_cli_exposes_apply_dry_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["apply", "dry-run", "--fixture", "plan.json"])

    assert args.command == "apply"
    assert args.apply_command == "dry-run"
    assert str(args.fixture) == "plan.json"
