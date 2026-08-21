# HH §5 read-ready gate

Evidence checklist for the HH read path after container recreate.

## Preconditions

- Compose volumes `hh-state` and `hh-profile` exist
- OAuth loopback publishes `127.0.0.1:8767` (not `8765`, which may be used by other local apps)

## Persistence probe

1. Seed synthetic (non-production) marker + token inside the running `hh` container:

```bash
docker compose exec -T hh python - <<'PY'
from job_search_hh.session import SessionPaths, confirm_login, auth_status
from job_search_hh.oauth import set_access_token, token_status
paths = SessionPaths.from_env()
confirm_login(paths, confirmed=True)
set_access_token("gate-test-token-not-a-real-secret", paths=paths, expires_in=3600)
print(auth_status(paths))
print(token_status(paths))
PY
```

2. Recreate the service without wiping named volumes:

```bash
docker compose up -d --force-recreate --wait hh
```

3. Expect after recreate:

```bash
docker compose exec -T hh python -m job_search_hh.cli auth status
# auth_session=present, login_ready=true

docker compose exec -T hh python -m job_search_hh.cli auth token-status
# access_token_present=true, source=token_file
```

Clear synthetic probe material afterwards:

```bash
docker compose exec -T hh python -m job_search_hh.cli auth clear
docker compose exec -T hh python -m job_search_hh.cli auth clear-token
```

## Gate verdict

When the probe passes, HH §5 read path is **read-ready**: session/token survive
recreate, sync remains fixture/live GET-only, BDD does not POST to HH, and live
apply stays `not_implemented` until explicitly authorized.
