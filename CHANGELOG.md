# Changelog

All notable changes are documented here using Keep a Changelog categories and
Semantic Versioning.

## Unreleased

### Changed

- Live create-only detail progress: emit `detail_planned` / `detail_fetched` /
  `unchanged_count` after every HH card (not only every 10th) so Web can show
  «Карточек HH загружено Z из Y».


### Added

- Detail extract: JSON-LD JobPosting `datePosted` (fallback page-state `publicationTime.$`) → `source_published_at` on NEW detail ingest; timezone normalized to UTC. No extra HH request; create-only unchanged.


### Fixed

- Vacancy detail Playwright extract: remove duplicate `const href` in `DETAIL_EXTRACT_JS` (Page.evaluate SyntaxError was mislabeled `vacancy_detail_failed` / `network_failure` while SERP still worked).
- Detail failure codes: `page_extract_failed` for evaluate/SyntaxError (not mapped to network recovery).

## [Unreleased]

### Changed

- Batch HH acquisition is **create-only**: SERP ids → Core
  `lookup-by-external-ids` → HH detail fetch only for NEW → ingest.
  Existing identities are recorded as SearchRunItem `unchanged` without
  detail download. Manual «Проверить обновления» refreshes one vacancy.
- Automation inherits create-only via `/vacancies/suitable` (no periodic
  refresh of all known HH vacancies).

### Added

- `POST /api/v1/vacancies/{external_id}/refresh-content` for owner-triggered
  single-vacancy detail → Core ingest.

### Fixed

- CAPTCHA evidence consistency: DOM title detector no longer matches bare
  ``robot``/``робот`` substrings (false positive on vacancy titles like
  «Technical Project Manager — Robotics»). Capture binds run_id / vacancy_id /
  page.url / title / matched_signals / screenshot from the same page object;
  inconsistent evidence → ``captcha_capture_invalid`` (not recoverable active
  CAPTCHA). CDP confirm probe no longer uses implicit ``pages[-1]``.

- CAPTCHA live handoff: persist challenge URL/title/screenshot *before*
  Playwright ``context.close``; distinguish capture A/B/C; never fabricate
  ``https://hh.ru/captcha``; ``open-challenge`` returns
  ``interactive_ready`` only when headed Chromium stays alive on ``:99``.
- CAPTCHA handoff lifecycle: HH API does not auto-reload bind-mounted source —
  recreate HH after capture-contract commits; ``public_challenge_view`` infers
  ``recovery_available`` from legacy states that only have ``challenge_url``.
- Post-CAPTCHA confirm: validate via authenticated resumes probe only —
  never re-open captured ``/account/captcha``; CDP observe headed solve state
  (active/solved); stop challenge browser after owner claim when not still on
  CAPTCHA; clear state only after session probe succeeds.
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
