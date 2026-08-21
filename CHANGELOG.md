# Changelog

All notable changes are documented here using Keep a Changelog categories and
Semantic Versioning.

## [Unreleased]

### Added

- Read-only HH vacancy sync into Core (`vacancies sync` CLI, fixture or public API).
- Fixture-based HH application sync into Core (`applications sync --fixture`).
- Fixture-based daily metrics sync into Core (`metrics sync --fixture`).
- Apply dry-run CLI that audits `would_send` without HH submit or Core writes.
- Gated limited-apply scaffold (`apply limited`) requiring env writes enable plus
  `--i-authorize-hh-writes`; live HH POST remains not implemented.
- Browser/auth runtime: Playwright Chromium + noVNC in the HH image, Compose
  loopback publish, `session status` reports `installed` when binaries are present.
- Operator login: `auth open-login` / `auth confirm --i-confirm-operator-login` /
  `auth clear`; `login_ready` only after explicit confirm; no CAPTCHA bypass.
- Live authenticated read: `applications|metrics sync` without `--fixture` uses
  Bearer GET `/negotiations` (metrics derived); requires `login_ready` + token;
  `hh_write_attempted=false`.
- OAuth token store: `auth oauth-url` / `exchange-code` / `set-token` /
  `token-status` / `clear-token`; secrets stay in state files, not CLI JSON.
- Loopback OAuth callback: `auth oauth-acquire` listens on `127.0.0.1` redirect
  and stores tokens after HH returns `code` (Compose publishes host loopback
  `:8765`).
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
