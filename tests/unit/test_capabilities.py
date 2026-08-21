"""Unit tests for the scaffold's conservative capability declaration."""

from job_search_hh.capabilities import current_capabilities


def test_external_writes_are_disabled_by_default() -> None:
    """An unconfigured host must never advertise permission to write to HH."""
    capabilities = current_capabilities()

    assert capabilities.external_writes_enabled is False
    assert capabilities.browser_automation in {"scaffold", "installed"}
    assert capabilities.browser_automation != "ready"
    assert capabilities.hh_api == "read-only"
