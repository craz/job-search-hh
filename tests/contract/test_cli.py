"""Contract tests for the versioned JSON capabilities command."""

from job_search_hh.cli import capabilities_envelope


def test_capabilities_envelope_has_stable_version_and_identity() -> None:
    """Consumers must receive schema version, component identity and safe defaults."""
    envelope = capabilities_envelope()

    assert envelope.schema_version == 1
    assert envelope.ok is True
    assert envelope.data["component"] == "job-search-hh"
    assert envelope.data["external_writes_enabled"] is False
