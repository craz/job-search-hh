"""Machine-readable declaration of the HH integration's safe current scope.

The scaffold deliberately performs no network or browser operation. Capability
metadata prevents consumers from mistaking an installed package for configured
automation and makes the external-write default explicit in tests and CLI output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from job_search_hh import __version__

COMPONENT_NAME: Final = "job-search-hh"


@dataclass(frozen=True)
class Capabilities:
    """Current integration readiness without secrets or environment inspection."""

    component: str
    version: str
    browser_automation: str
    hh_api: str
    external_writes_enabled: bool

    def to_dict(self) -> dict[str, str | bool]:
        """Return a JSON-compatible copy without exposing mutable internal state."""
        return asdict(self)


def current_capabilities() -> Capabilities:
    """Describe implemented behavior with conservative external-write defaults."""
    return Capabilities(
        component=COMPONENT_NAME,
        version=__version__,
        browser_automation="not-configured",
        hh_api="not-configured",
        external_writes_enabled=False,
    )
