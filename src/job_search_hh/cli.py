"""Versioned JSON command-line interface for HH integration diagnostics."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from job_search_hh.capabilities import current_capabilities


@dataclass(frozen=True)
class Envelope:
    """Stable version-1 machine envelope for host automation and future Hermes use."""

    schema_version: int
    ok: bool
    data: dict[str, str | bool]


def build_parser() -> argparse.ArgumentParser:
    """Define diagnostics only; auth, sync and apply commands are not implemented."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capabilities",))
    return parser


def capabilities_envelope() -> Envelope:
    """Build a successful response that keeps external writes explicitly disabled."""
    return Envelope(schema_version=1, ok=True, data=current_capabilities().to_dict())


def main(argv: Sequence[str] | None = None) -> int:
    """Print exactly one JSON envelope and return a process-compatible status."""
    build_parser().parse_args(argv)
    print(json.dumps(asdict(capabilities_envelope()), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
