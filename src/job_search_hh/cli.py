"""Versioned JSON command-line interface for HH read-only vacancy sync."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from job_search_hh.capabilities import current_capabilities
from job_search_hh.config import Settings
from job_search_hh.core_client import CoreClient
from job_search_hh.providers import FixtureProvider, HttpHhApi
from job_search_hh.sync import SyncError, sync_vacancies


@dataclass(frozen=True)
class Envelope:
    """Stable version-1 machine envelope for host automation and future Hermes use."""

    schema_version: int
    ok: bool
    data: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    """Define capabilities and read-only vacancy sync; apply remains unavailable."""
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
    return parser


def capabilities_envelope() -> Envelope:
    """Build a successful response that keeps external writes explicitly disabled."""
    return Envelope(schema_version=1, ok=True, data=current_capabilities().to_dict())


def sync_envelope(args: argparse.Namespace) -> Envelope:
    """Run one read-only sync and wrap the report for machine consumers."""
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


def main(argv: Sequence[str] | None = None) -> int:
    """Print exactly one JSON envelope and return a process-compatible status."""
    args = build_parser().parse_args(argv)
    if args.command == "capabilities":
        envelope = capabilities_envelope()
    elif args.command == "vacancies" and args.vacancies_command == "sync":
        envelope = sync_envelope(args)
    else:  # pragma: no cover - argparse enforces choices
        return 2
    print(json.dumps(asdict(envelope), ensure_ascii=False, sort_keys=True))
    return 0 if envelope.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
