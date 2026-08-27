# Changelog

All notable changes are documented here using Keep a Changelog categories and
Semantic Versioning.

## [Unreleased]

### Added

- R2.2.4 SearchRun orchestration: `POST /api/v1/vacancies/search` and
  `vacancies search` CLI — SearchProfile → browser acquire → Core ingest →
  SearchRunItem → finalize (immutable snapshots; no fake page_size).
- Fixture-based HH application sync into Core (`applications sync --fixture`).
- Fixture-based daily metrics sync into Core (`metrics sync --fixture`).
- Apply dry-run CLI that audits `would_send` without HH submit or Core writes.
- Gated limited apply live transport: dual-gate + login_ready/token → POST
  `/negotiations`; CAPTCHA/auth responses stop the run; default env keeps writes off.
- Browser/auth runtime: Playwright Chromium + noVNC in the HH image, Compose
  loopback publish, `session status` reports `installed` when binaries are present.
- Operator login: `auth open-login` / `auth confirm --i-confirm-operator-login` /
  `auth clear`; `login_ready` only after explicit confirm; no CAPTCHA bypass.
- Live authenticated read: `applications|metrics sync` without `--fixture` uses
  Bearer GET `/negotiations` plus `/resumes/mine` view counters for metrics;
  requires `login_ready` + token; `hh_write_attempted=false`.
- OAuth token store: `auth oauth-url` / `exchange-code` / `set-token` /
  `token-status` / `clear-token`; secrets stay in state files, not CLI JSON.
- Loopback OAuth callback: `auth oauth-acquire` listens on `127.0.0.1` redirect
  and stores tokens after HH returns `code` (Compose publishes host loopback
  `:8767`).
- Read-ready gate runbook: session/token persistence across HH container
  recreate (`docs/runbooks/hh-read-gate.md`).
- Browser/auth scaffold CLI (`session`/`auth status`) and profile lock remain the
  operator-facing diagnostics until login is confirmed.
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
