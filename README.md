# Job Search HH

Safe HeadHunter integration boundary for a local job-search system. This
repository owns read-only HH vacancy/application sync into Core, future
Chromium/Playwright automation, persistent session state and guarded apply
workflows. It communicates with Core only through versioned public contracts.

## Current status

Read-only vacancy sync, fixture application sync and fixture daily metrics sync
are implemented. Public HH search (or a fixture) writes vacancies through
`POST /api/v1/vacancies`; existing negotiations/applications from a fixture write
through `POST /api/v1/applications`; daily snapshots write through
`PUT /api/v1/metrics/{date}` with fingerprint idempotency keys.
Capabilities report `hh_api=read-only` and `external_writes_enabled=false`.
Browser automation becomes `installed` inside the HH image (Chromium/Playwright/
noVNC). Operator login uses loopback noVNC plus `auth open-login` /
`auth confirm --i-confirm-operator-login`; cookies stay in the profile volume and
are never printed. Live OAuth automation, CAPTCHA bypass and chats are not
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
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh applications sync --fixture path/to/apps.json
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh metrics sync --fixture path/to/metrics.json
uv run job-search-hh apply dry-run --fixture path/to/apply_plan.json
uv run job-search-hh apply limited --fixture path/to/apply_plan.json --i-authorize-hh-writes
uv run job-search-hh session status
uv run job-search-hh auth status
uv run job-search-hh auth open-login --detach
uv run job-search-hh auth confirm --i-confirm-operator-login
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
[operator login runbook](docs/runbooks/operator-novnc-login.md),
[safe scaffold](docs/specs/safe-scaffold.md) and executable Gherkin under
`tests/features/`.

## License

MIT. See [LICENSE](LICENSE).
