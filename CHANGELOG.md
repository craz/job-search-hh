# Changelog

All notable changes are documented here using Keep a Changelog categories and
Semantic Versioning.

## [Unreleased]

### Added

- Read-only HH vacancy sync into Core (`vacancies sync` CLI, fixture or public API).
- Fixture-based HH application sync into Core (`applications sync --fixture`).
- Fixture-based daily metrics sync into Core (`metrics sync --fixture`).
- Apply dry-run CLI that audits `would_send` without HH submit or Core writes.
- Normalization to Core VacancyCreate/ApplicationCreate/DailyMetricUpdate with
  stable `source=hh` and idempotent keys.
- Capabilities report `hh_api=read-only` while keeping `external_writes_enabled=false`.

### Changed

- Safe scaffold docs now treat vacancy Core sync as implemented for the read path.

## [0.1.0]

### Added

- Safe Python/direnv/Make scaffold and versioned JSON capabilities CLI.
- Explicit disabled external-write and not-configured browser/API states.
- Unit, contract and executable BDD quality gates.
