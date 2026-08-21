# HH loopback OAuth callback listener

## User Story

```text
Как оператор системы поиска работы,
Я хочу чтобы HH container принял OAuth code на 127.0.0.1 redirect,
Чтобы не копировать code вручную из URL.
```

## Implemented

- `auth oauth-acquire` binds a loopback-only HTTP listener to the configured
  `JOB_SEARCH_HH_REDIRECT_URI` (must be `http://127.0.0.1|localhost|::1`);
- on `GET .../oauth/callback?code=...` exchanges the code and stores tokens via
  the existing private token store;
- `--detach` returns `authorize_url` immediately and listens in a child process;
- Compose publishes `127.0.0.1:8767:8767` for host-browser redirects;
- CLI JSON still never includes raw `access_token` / `refresh_token` /
  `client_secret`.

## Non-scope

Non-loopback redirect hosts, automatic browser/noVNC navigation, CAPTCHA bypass
and live HH write transport.
