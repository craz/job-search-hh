# Job Search HH

Safe HeadHunter integration boundary for a local job-search system. This
repository owns read-only HH vacancy/application sync into Core, future
Chromium/Playwright automation, persistent session state and guarded apply
workflows. It communicates with Core only through versioned public contracts.

## Current status

Read-only vacancy sync and fixture-based application sync are implemented.
Public HH search (or a fixture) writes vacancies through
`POST /api/v1/vacancies`; existing negotiations/applications from a fixture write
through `POST /api/v1/applications` with stable `source=hh` and idempotent keys.
Capabilities report `hh_api=read-only` and `external_writes_enabled=false`.
Browser automation, OAuth, apply and chats are not implemented.

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
```

Offline vacancy fixture sync:

```bash
CORE_API_URL=http://127.0.0.1:8000 uv run job-search-hh vacancies sync --fixture path/to/items.json
```

Manual virtualenv activation is not required. `make bootstrap` uses the checked-in
lock and `.venv`; it never installs Playwright browsers in this slice.

## Safety boundary

- Real HH writes require explicit authorization and dedicated gates.
- Tokens, cookies and browser profile are runtime-only data.
- CAPTCHA/auth failures stop automation instead of attempting bypasses.
- Future browser state lives in an HH-only named volume.
- Core data is accessed through HTTP/JSON contracts, never PostgreSQL.

See [vacancy sync](docs/specs/vacancy-sync.md),
[application sync](docs/specs/application-sync.md),
[safe scaffold](docs/specs/safe-scaffold.md) and executable Gherkin under
`tests/features/`.

## License

MIT. See [LICENSE](LICENSE).
