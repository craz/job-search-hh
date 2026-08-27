# Job Search HH

Safe HeadHunter integration boundary for a local job-search system. This
repository owns read-only HH vacancy/application sync into Core, future
Chromium/Playwright automation, persistent session state and guarded apply
workflows. It communicates with Core only through versioned public contracts.

## Current status

Read-only vacancy sync is implemented. Applications and daily metrics sync
accept a fixture or, without `--fixture`, an authenticated GET `/negotiations`
(requires `login_ready` plus access token). Live metrics also read
`GET /resumes/mine` for `views_total`/`views_new` when the app scope allows it.
Public HH search writes vacancies through `POST /api/v1/vacancies`; applications
and metrics write only to Core.
Capabilities report `hh_api=read-only` and `external_writes_enabled=false`.
`apply limited` can POST `/negotiations` only when env writes are enabled, the
CLI flag is set, and login_ready+token are present; Compose keeps writes off.
Browser automation becomes `installed` inside the HH image (Chromium/Playwright/
noVNC). Operator login uses loopback noVNC plus `auth open-login` /
`auth confirm --i-confirm-operator-login`; cookies stay in the profile volume and
are never printed. OAuth token storage (`auth oauth-url` / `exchange-code` /
`set-token` / `token-status`) keeps secrets out of CLI JSON. Loopback OAuth
callback (`auth oauth-acquire` on `127.0.0.1:8767`) is implemented. Product-facing
connection status (`connection status`, HTTP `GET /api/v1/connection`) maps
session/token markers to connected / not_authorized / expired / action_required /
unavailable without claiming endpoint permissions. Account context
(`account status`, HTTP `GET /api/v1/account`) normalizes official `GET /me`
identity fields only. Under the workspace Compose stack, a loopback host HTTP
proxy is bridged into Docker by `make up` / `make dev` (workspace runbook
`docs/runbooks/hh-docker-host-proxy.md`). CAPTCHA bypass and chats are not
implemented.

## Quick start

Requirements: Python 3.12, `uv` and Make. A reachable Core API is required for
live sync.

```bash
direnv allow
make bootstrap
make test
make smoke
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh vacancies sync --text "python" --per-page 3
# SearchRun orchestration (R2.2.4): persisted SearchProfile → browser → Core ingest
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh vacancies search --search-profile-id '<uuid>' --max-pages 1
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh applications sync --fixture path/to/apps.json
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh metrics sync --fixture path/to/metrics.json
# live authenticated read (no HH write): login_ready + access token required
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh applications sync
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh metrics sync
uv run job-search-hh apply dry-run --fixture path/to/apply_plan.json
uv run job-search-hh apply limited --fixture path/to/apply_plan.json --i-authorize-hh-writes
uv run job-search-hh session status
uv run job-search-hh connection status
uv run job-search-hh account status
uv run job-search-hh resumes list
uv run job-search-hh auth status
uv run job-search-hh auth open-login --detach
uv run job-search-hh auth confirm --i-confirm-operator-login
uv run job-search-hh auth oauth-url
uv run job-search-hh auth oauth-acquire --detach
uv run job-search-hh auth exchange-code --code 'PASTE_CODE'
uv run job-search-hh auth token-status
```

Offline vacancy fixture sync:

```bash
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh vacancies sync --fixture path/to/items.json
```

Manual virtualenv activation is not required. `make bootstrap` uses the checked-in
lock; Playwright browsers for the HH image are installed in Docker, not by host
`make bootstrap`.

## Safety boundary

- Real HH writes require explicit authorization and dedicated gates.
- Tokens, cookies and browser profile are runtime-only data.
- CAPTCHA/auth failures stop automation instead of attempting bypasses.
- Future browser state lives in an HH-only named volume.
- Core data is accessed through HTTP/JSON contracts, never PostgreSQL.

See [vacancy sync](docs/specs/vacancy-sync.md),
[application sync](docs/specs/application-sync.md),
[metrics sync](docs/specs/metrics-sync.md),
[apply dry-run](docs/specs/apply-dry-run.md),
[apply limited](docs/specs/apply-limited.md),
[browser/auth scaffold](docs/specs/browser-auth-scaffold.md),
[operator noVNC login](docs/specs/operator-novnc-login.md),
[live authenticated read](docs/specs/live-authenticated-read.md),
[resume-views metrics](docs/specs/resume-views-metrics.md),
[oauth token store](docs/specs/oauth-token-store.md),
[oauth loopback callback](docs/specs/oauth-loopback-callback.md),
[connection status](docs/specs/connection-status.md),
[account profile](docs/specs/account-profile.md),
[HH read gate](docs/runbooks/hh-read-gate.md),
[operator login runbook](docs/runbooks/operator-novnc-login.md),
[safe scaffold](docs/specs/safe-scaffold.md) and executable Gherkin under
`tests/features/`.

## License

MIT. See [LICENSE](LICENSE).
