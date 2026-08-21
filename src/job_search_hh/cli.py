"""Versioned JSON command-line interface for HH sync, dry-run and gated limited apply."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from job_search_hh.apply import ApplyError, dry_run_apply, limited_apply, load_apply_plan
from job_search_hh.capabilities import current_capabilities
from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient
from job_search_hh.live_auth import LiveAuthError, require_authenticated_read
from job_search_hh.oauth import (
    OAuthError,
    build_authorize_url,
    clear_token_record,
    exchange_authorization_code,
    set_access_token,
    token_status,
)
from job_search_hh.oauth_callback import oauth_acquire
from job_search_hh.providers import AuthenticatedHhApi, FixtureProvider, HttpHhApi
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
        "sync",
        help="Import HH applications into Core (fixture or authenticated GET /negotiations)",
    )
    app_sync.add_argument(
        "--fixture",
        type=Path,
        help="Synthetic negotiations JSON; omit for live authenticated GET (no HH write)",
    )

    metrics = sub.add_parser("metrics", help="Read-only daily metric operations")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    metric_sync = metrics_sub.add_parser(
        "sync",
        help="Import daily metrics into Core (fixture or derived from authenticated negotiations)",
    )
    metric_sync.add_argument(
        "--fixture",
        type=Path,
        help="Synthetic daily metrics JSON; omit for live derived snapshot (no HH write)",
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
    oauth_url = auth_sub.add_parser(
        "oauth-url",
        help="Build HH OAuth authorize URL (never prints client_secret)",
    )
    oauth_url.add_argument("--state", default="job-search-hh", help="OAuth state parameter")
    exchange = auth_sub.add_parser(
        "exchange-code",
        help="Exchange authorization code for tokens and store them privately",
    )
    exchange.add_argument("--code", required=True, help="Authorization code from redirect")
    set_token = auth_sub.add_parser(
        "set-token",
        help="Store access token from file or stdin (token never appears in JSON)",
    )
    set_token_src = set_token.add_mutually_exclusive_group(required=True)
    set_token_src.add_argument("--token-file", type=Path, help="Read access token from a file")
    set_token_src.add_argument(
        "--from-stdin",
        action="store_true",
        help="Read access token from stdin",
    )
    set_token.add_argument("--refresh-token-file", type=Path, help="Optional refresh token file")
    set_token.add_argument("--expires-in", type=int, help="Optional lifetime seconds")
    auth_sub.add_parser("token-status", help="Report token presence without dumping secrets")
    auth_sub.add_parser("clear-token", help="Remove stored OAuth token files")
    acquire = auth_sub.add_parser(
        "oauth-acquire",
        help="Listen on loopback redirect URI for OAuth code and store tokens",
    )
    acquire.add_argument("--state", default="job-search-hh", help="OAuth state parameter")
    acquire.add_argument(
        "--wait-seconds",
        type=float,
        default=300.0,
        help="How long the callback listener waits for the redirect",
    )
    acquire.add_argument(
        "--detach",
        action="store_true",
        help="Start listener in background and return authorize_url immediately",
    )
    acquire.add_argument(
        "--foreground",
        action="store_true",
        help=argparse.SUPPRESS,
    )
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
    """Import applications via fixture or authenticated GET; never POST to HH."""
    settings = Settings.from_env()
    try:
        if args.fixture is not None:
            provider: FixtureProvider | AuthenticatedHhApi = FixtureProvider.from_path(args.fixture)
            transport = "fixture"
        else:
            token = require_authenticated_read()
            provider = AuthenticatedHhApi(
                settings.hh_api_url,
                settings.user_agent,
                settings.timeout_seconds,
                token,
            )
            transport = "authenticated_api"
        core = CoreClient(settings.core_url, settings.timeout_seconds)
        report = sync_applications(provider, core)
    except (LiveAuthError, SyncError) as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    report["transport"] = transport
    return Envelope(schema_version=1, ok=True, data=report)


def metric_sync_envelope(args: argparse.Namespace) -> Envelope:
    """Import metrics via fixture or authenticated derived snapshot; never write HH."""
    settings = Settings.from_env()
    try:
        if args.fixture is not None:
            provider: FixtureProvider | AuthenticatedHhApi = FixtureProvider.from_path(args.fixture)
            transport = "fixture"
        else:
            token = require_authenticated_read()
            provider = AuthenticatedHhApi(
                settings.hh_api_url,
                settings.user_agent,
                settings.timeout_seconds,
                token,
            )
            transport = "authenticated_api"
        core = CoreClient(settings.core_url, settings.timeout_seconds)
        report = sync_metrics(provider, core)
    except (LiveAuthError, SyncError) as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    report["transport"] = transport
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


def auth_oauth_url_envelope(args: argparse.Namespace) -> Envelope:
    """Return authorize URL metadata without client_secret."""
    try:
        report = build_authorize_url(state=str(args.state))
    except OAuthError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def auth_exchange_code_envelope(args: argparse.Namespace) -> Envelope:
    """Exchange code and return presence status only."""
    try:
        report = exchange_authorization_code(str(args.code))
    except OAuthError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


def auth_set_token_envelope(args: argparse.Namespace) -> Envelope:
    """Store token from file/stdin; JSON never includes the secret value."""
    try:
        if args.from_stdin:
            access = sys.stdin.read()
        else:
            access = Path(args.token_file).read_text(encoding="utf-8")
        refresh = None
        if args.refresh_token_file is not None:
            refresh = Path(args.refresh_token_file).read_text(encoding="utf-8")
        report = set_access_token(
            access,
            refresh_token=refresh,
            expires_in=args.expires_in,
        )
    except (OSError, OAuthError) as error:
        message = str(error) if isinstance(error, OAuthError) else "token_read_failed"
        return Envelope(schema_version=1, ok=False, data={"error": message})
    return Envelope(schema_version=1, ok=True, data=report)


def auth_token_status_envelope() -> Envelope:
    """Report whether an access token is available without printing it."""
    return Envelope(schema_version=1, ok=True, data=token_status())


def auth_clear_token_envelope() -> Envelope:
    """Delete persisted token files under the HH state directory."""
    return Envelope(schema_version=1, ok=True, data=clear_token_record())


def auth_oauth_acquire_envelope(args: argparse.Namespace) -> Envelope:
    """Run loopback callback acquire; JSON never includes raw tokens."""
    try:
        report = oauth_acquire(
            state=str(args.state),
            wait_seconds=float(args.wait_seconds),
            detach=bool(args.detach) and not bool(args.foreground),
        )
    except OAuthError as error:
        return Envelope(schema_version=1, ok=False, data={"error": str(error)})
    return Envelope(schema_version=1, ok=True, data=report)


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
    elif args.command == "auth" and args.auth_command == "oauth-url":
        envelope = auth_oauth_url_envelope(args)
    elif args.command == "auth" and args.auth_command == "exchange-code":
        envelope = auth_exchange_code_envelope(args)
    elif args.command == "auth" and args.auth_command == "set-token":
        envelope = auth_set_token_envelope(args)
    elif args.command == "auth" and args.auth_command == "token-status":
        envelope = auth_token_status_envelope()
    elif args.command == "auth" and args.auth_command == "clear-token":
        envelope = auth_clear_token_envelope()
    elif args.command == "auth" and args.auth_command == "oauth-acquire":
        envelope = auth_oauth_acquire_envelope(args)
    else:  # pragma: no cover - argparse enforces choices
        return 2
    printed = json.dumps(asdict(envelope), ensure_ascii=False, sort_keys=True)
    # Defense in depth: refuse to emit raw secret fields in the public envelope.
    if (
        '"access_token":' in printed
        or '"refresh_token":' in printed
        or '"client_secret":' in printed
    ):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "data": {"error": "token_leak_blocked"},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(printed)
    return 0 if envelope.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
