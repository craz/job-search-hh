"""Versioned JSON command-line interface for HH sync, dry-run and gated limited apply."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from job_search_hh.apply import ApplyError, dry_run_apply, limited_apply, load_apply_plan
from job_search_hh.capabilities import current_capabilities
from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient
from job_search_hh.providers import FixtureProvider, HttpHhApi
from job_search_hh.session import (
    SessionError,
    auth_status,
    clear_login,
    confirm_login,
    open_login,
    session_status,
)
from job_search_hh.sync import SyncError, sync_applications, sync_metrics, sync_vacancies


@dataclass(frozen=True)
class Envelope:
    """Stable version-1 machine envelope for host automation and future Hermes use."""

    schema_version: int
    ok: bool
    data: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    """Define sync, dry-run and gated limited apply; live HH POST stays unimplemented."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("capabilities", help="Report safe integration capabilities")

    vacancies = sub.add_parser("vacancies", help="Read-only vacancy operations")
    vacancies_sub = vacancies.add_subparsers(dest="vacancies_command", required=True)
    sync = vacancies_sub.add_parser("sync", help="Fetch public HH vacancies into Core")
    sync.add_argument("--text", default="python", help="HH public search query")
    sync.add_argument("--per-page", type=int, default=5, help="Page size (1-50)")
    sync.add_argument(
        "--fixture",
        type=Path,
        help="Synthetic HH JSON fixture instead of the live public API",
    )

    applications = sub.add_parser("applications", help="Read-only application operations")
    applications_sub = applications.add_subparsers(dest="applications_command", required=True)
    app_sync = applications_sub.add_parser(
        "sync", help="Import existing HH applications into Core from a fixture"
    )
    app_sync.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="Synthetic negotiations/applications JSON (live auth API is out of scope)",
    )

    metrics = sub.add_parser("metrics", help="Read-only daily metric operations")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    metric_sync = metrics_sub.add_parser(
        "sync", help="Import daily metric snapshots into Core from a fixture"
    )
    metric_sync.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="Synthetic daily metrics JSON (live HH stats API is out of scope)",
    )

    apply = sub.add_parser("apply", help="Guarded application operations")
    apply_sub = apply.add_subparsers(dest="apply_command", required=True)
    dry_run = apply_sub.add_parser("dry-run", help="Simulate HH apply payloads without submitting")
    dry_run.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="Synthetic apply plan JSON (never contacts HH write endpoints)",
    )
    limited = apply_sub.add_parser(
        "limited",
        help="Gated limited apply scaffold (requires env+flag; live POST not implemented)",
    )
    limited.add_argument("--fixture", type=Path, required=True, help="Synthetic apply plan JSON")
    limited.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max applications per run (default from JOB_SEARCH_HH_APPLY_LIMIT)",
    )
    limited.add_argument(
        "--i-authorize-hh-writes",
        action="store_true",
        help="Explicit operator authorization required together with env writes enable",
    )

    session = sub.add_parser("session", help="Browser/profile session scaffold diagnostics")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser(
        "status", help="Report profile/state scaffold without launching Chromium"
    )

    auth = sub.add_parser("auth", help="Operator authentication via noVNC")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("status", help="Report auth session marker without HH login")
    open_login_cmd = auth_sub.add_parser(
        "open-login",
        help="Open HH login in headed Chromium for loopback noVNC (no CAPTCHA bypass)",
    )
    open_login_cmd.add_argument(
        "--login-url",
        default="https://hh.ru/account/login",
        help="HH login page opened in the persistent profile",
    )
    open_login_cmd.add_argument(
        "--detach",
        action="store_true",
        help="Start browser in a background process and return immediately",
    )
    open_login_cmd.add_argument(
        "--foreground",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    confirm = auth_sub.add_parser(
        "confirm",
        help="Record operator confirmation that interactive HH login succeeded",
    )
    confirm.add_argument(
        "--i-confirm-operator-login",
        action="store_true",
        help="Required explicit confirmation; does not capture cookies into JSON",
    )
    auth_sub.add_parser("clear", help="Clear session marker without deleting the profile")
    return parser


def capabilities_envelope() -> Envelope:
    """Build a successful response that keeps external writes explicitly disabled."""
    return Envelope(schema_version=1, ok=True, data=current_capabilities().to_dict())


def vacancy_sync_envelope(args: argparse.Namespace) -> Envelope:
    """Run one read-only vacancy sync and wrap the report for machine consumers."""
    settings = Settings.from_env()
    if args.fixture is not None:
        provider: FixtureProvider | HttpHhApi = FixtureProvider.from_path(args.fixture)
    else:
        provider = HttpHhApi(settings.hh_api_url, settings.user_agent, settings.timeout_seconds)
    core = CoreClient(settings.core_url, settings.timeout_seconds)
    try:
        report = sync_vacancies(
            provider, core, text=args.text, per_page=max(1, min(args.per_page, 50))
        )
    except SyncError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def application_sync_envelope(args: argparse.Namespace) -> Envelope:
    """Import fixture applications without contacting authenticated HH write APIs."""
    settings = Settings.from_env()
    provider = FixtureProvider.from_path(args.fixture)
    core = CoreClient(settings.core_url, settings.timeout_seconds)
    try:
        report = sync_applications(provider, core)
    except SyncError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def metric_sync_envelope(args: argparse.Namespace) -> Envelope:
    """Import fixture daily metrics without contacting authenticated HH stats APIs."""
    settings = Settings.from_env()
    provider = FixtureProvider.from_path(args.fixture)
    core = CoreClient(settings.core_url, settings.timeout_seconds)
    try:
        report = sync_metrics(provider, core)
    except SyncError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def apply_dry_run_envelope(args: argparse.Namespace) -> Envelope:
    """Simulate apply payloads and return audit JSON without HH or Core writes."""
    try:
        report = dry_run_apply(load_apply_plan(args.fixture))
    except ApplyError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    ok = not report["errors"] and report["hh_write_attempted"] is False
    return Envelope(schema_version=1, ok=ok, data=report)


def apply_limited_envelope(args: argparse.Namespace) -> Envelope:
    """Refuse unless dual-authorized; still do not POST to HH in this scaffold."""
    settings = Settings.from_env()
    limit = args.limit if args.limit is not None else settings.apply_limit_per_run
    try:
        report = limited_apply(
            load_apply_plan(args.fixture),
            external_writes_enabled=settings.external_writes_enabled,
            authorized=bool(args.i_authorize_hh_writes),
            limit=limit,
        )
    except ApplyError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    ok = report["execution"] == "not_implemented" and report["hh_write_attempted"] is False
    return Envelope(schema_version=1, ok=ok, data=report)


def session_status_envelope() -> Envelope:
    """Report browser/profile scaffold without launching Chromium."""
    return Envelope(schema_version=1, ok=True, data=session_status())


def auth_status_envelope() -> Envelope:
    """Report auth marker without performing HH login."""
    return Envelope(schema_version=1, ok=True, data=auth_status())


def auth_open_login_envelope(args: argparse.Namespace) -> Envelope:
    """Open headed login for noVNC or refuse with a stable session error."""
    try:
        report = open_login(
            login_url=str(args.login_url),
            detach=bool(args.detach) and not bool(args.foreground),
        )
    except SessionError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def auth_confirm_envelope(args: argparse.Namespace) -> Envelope:
    """Persist present marker only after explicit operator confirmation."""
    try:
        report = confirm_login(confirmed=bool(args.i_confirm_operator_login))
    except SessionError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def auth_clear_envelope() -> Envelope:
    """Drop the session marker while keeping the Chromium profile volume."""
    return Envelope(schema_version=1, ok=True, data=clear_login())


def main(argv: Sequence[str] | None = None) -> int:
    """Print exactly one JSON envelope and return a process-compatible status."""
    args = build_parser().parse_args(argv)
    if args.command == "capabilities":
        envelope = capabilities_envelope()
    elif args.command == "vacancies" and args.vacancies_command == "sync":
        envelope = vacancy_sync_envelope(args)
    elif args.command == "applications" and args.applications_command == "sync":
        envelope = application_sync_envelope(args)
    elif args.command == "metrics" and args.metrics_command == "sync":
        envelope = metric_sync_envelope(args)
    elif args.command == "apply" and args.apply_command == "dry-run":
        envelope = apply_dry_run_envelope(args)
    elif args.command == "apply" and args.apply_command == "limited":
        envelope = apply_limited_envelope(args)
    elif args.command == "session" and args.session_command == "status":
        envelope = session_status_envelope()
    elif args.command == "auth" and args.auth_command == "status":
        envelope = auth_status_envelope()
    elif args.command == "auth" and args.auth_command == "open-login":
        envelope = auth_open_login_envelope(args)
    elif args.command == "auth" and args.auth_command == "confirm":
        envelope = auth_confirm_envelope(args)
    elif args.command == "auth" and args.auth_command == "clear":
        envelope = auth_clear_envelope()
    else:  # pragma: no cover - argparse enforces choices
        return 2
    print(json.dumps(asdict(envelope), ensure_ascii=False, sort_keys=True))
    return 0 if envelope.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
