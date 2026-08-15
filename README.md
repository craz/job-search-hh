# Job Search HH

Safe HeadHunter integration boundary for a local job-search system. This
repository will own HH API access, Chromium/Playwright automation, persistent
session state and guarded apply workflows. It communicates with Core only through
versioned public contracts.

## Current status

The safe platform scaffold is implemented. It exposes a versioned capabilities
CLI and explicitly reports browser/API automation as `not-configured` with
external writes disabled. No HH request, browser launch or application submission
is implemented yet.

## Quick start

Requirements: Python 3.12, `uv` and Make.

```bash
direnv allow
make bootstrap
make test
make smoke
```

Manual virtualenv activation is not required. `make bootstrap` uses the checked-in
lock and `.venv`; it never installs Playwright browsers in this scaffold.

## Safety boundary

- Real HH writes require explicit authorization and dedicated gates.
- Tokens, cookies and browser profile are runtime-only data.
- CAPTCHA/auth failures stop automation instead of attempting bypasses.
- Future browser state lives in an HH-only named volume.
- Core data is accessed through HTTP/JSON contracts, never PostgreSQL.

See [the feature spec](docs/specs/safe-scaffold.md) and executable
[Gherkin scenario](tests/features/safe_scaffold.feature).

## License

MIT. See [LICENSE](LICENSE).

