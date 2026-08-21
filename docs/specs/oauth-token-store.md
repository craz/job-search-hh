# HH OAuth token acquisition and private storage

## User Story

```text
Как оператор системы поиска работы,
Я хочу получить OAuth access token и сохранить его в HH state,
Чтобы live authenticated reads работали без печати секретов в CLI JSON.
```

## Implemented

- `auth oauth-url` builds authorize URL from `JOB_SEARCH_HH_CLIENT_ID` /
  `HH_CLIENT_ID` and redirect URI (never prints `client_secret`);
- `auth exchange-code --code` exchanges the code via POST `/oauth/token` and
  stores `hh_token.json` + legacy `access_token` with mode `0600`;
- `auth set-token --token-file|--from-stdin` for manual token import;
- `auth token-status` / `auth clear-token` report presence or wipe files without
  dumping secrets;
- `load_access_token` prefers env, then `hh_token.json` (with refresh near
  expiry), then plain `access_token` file;
- CLI JSON refuses envelopes containing raw `access_token` / `refresh_token` /
  `client_secret` fields.

## Non-scope

Non-loopback redirect hosts and automatic browser navigation remain in
[oauth-loopback-callback.md](oauth-loopback-callback.md) / future slices.
CAPTCHA bypass and live HH write transport stay out of scope.
