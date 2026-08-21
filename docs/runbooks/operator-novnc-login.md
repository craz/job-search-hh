# Operator HH login via loopback noVNC

Prerequisites: Compose service `hh` is healthy with Chromium/noVNC installed.

1. Open noVNC only on the host loopback: http://127.0.0.1:6080/
2. Start headed HH login (detached JSON returns immediately):

```bash
docker compose exec -T hh python -m job_search_hh.cli auth open-login --detach
```

3. In noVNC, complete HH login yourself. Stop on CAPTCHA/uncertain UI; do not
   ask automation to bypass it.
4. Confirm the operator session marker (no cookies are printed):

```bash
docker compose exec -T hh python -m job_search_hh.cli auth confirm \
  --i-confirm-operator-login
```

5. Check readiness:

```bash
docker compose exec -T hh python -m job_search_hh.cli auth status
```

Expected: `auth_session=present`, `login_ready=true`.

6. For live authenticated API reads, place a user OAuth access token in the HH
   state volume (never commit it) or set `JOB_SEARCH_HH_ACCESS_TOKEN`, then:

```bash
docker compose exec -T hh python -m job_search_hh.cli applications sync
docker compose exec -T hh python -m job_search_hh.cli metrics sync
```

Clear the marker without wiping the profile volume:

```bash
docker compose exec -T hh python -m job_search_hh.cli auth clear
```
