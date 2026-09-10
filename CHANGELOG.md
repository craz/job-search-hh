# Changelog

All notable changes are documented here using Keep a Changelog categories and
Semantic Versioning.

## [Unreleased]

### Fixed

- CAPTCHA live handoff: persist challenge URL/title/screenshot *before*
  Playwright ``context.close``; distinguish capture A/B/C; never fabricate
  ``https://hh.ru/captcha``; ``open-challenge`` returns
  ``interactive_ready`` only when headed Chromium stays alive on ``:99``.
- CAPTCHA handoff lifecycle: HH API does not auto-reload bind-mounted source —
  recreate HH after capture-contract commits; ``public_challenge_view`` infers
  ``recovery_available`` from legacy states that only have ``challenge_url``.
- Post-CAPTCHA «Проверить снова»: detect live challenge Chromium / profile lock
  with an explicit «окно ещё открыто» message; heal stale locks after close;
  clear challenge only after probe; promote connection via confirm_login.
- CAPTCHA operator handoff: capture screenshot from the challenged headless
  scraper context, persist private challenge state, open headed Chromium at the
  *challenge URL* (not `/account/login`), optional Telegram DM notify only when
  `HH_CAPTCHA_TG` + `TELEGRAM_DM_*` are set. Do not advertise login noVNC as the
  CAPTCHA recovery path.
- Suitable/detail acquisition fail-fast on HH CAPTCHA/challenge pages (URL/title/DOM),
  stops further vacancy detail loading, persists `browser_captcha_or_action_required`,
  and surfaces `open_challenge` recovery — no CAPTCHA bypass.
- Resume-suitable acquisition paginates with `execution.max_pages` + `execution.start_page`
  (continuation), exposes HH-style `found` / `pages` / `next_page` / `more_remaining`, and
  scales detail ingest to the page cap so Web is not stuck on silent first-page-only runs.

### Added

- Persist SearchRun mid-run progress after each HH SERP page (and ingest phase)
  via Core `POST /search-runs/{id}/progress` so Web can show live page/checked counts.

- R2.4.1b vacancy source-status check: `GET /api/v1/vacancies/{external_id}/source-status`
  — browser RO detail extract reports `active` / `archived` / `unknown`; auth,
  CAPTCHA and transport failures never yield `archived`; no Core writes.
- R2.2.5 primary `resume_suitable` orchestration: `POST /api/v1/vacancies/suitable`

  — active resume → suitable SERP (`order_by=publication_time`) → SERP guard →
  detail → Core ingest; `source_total` preserved separately from processed count.
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
