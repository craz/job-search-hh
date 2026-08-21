# HH operator login via loopback noVNC

## User Story

```text
Как оператор системы поиска работы,
Я хочу открыть HH login в Chromium через loopback noVNC и подтвердить сессию,
Чтобы auth status стал present/login_ready без обхода CAPTCHA и без дампа cookies.
```

## Implemented

- CLI `auth open-login` opens headed Chromium on the persistent profile (optional
  `--detach`); CAPTCHA bypass is explicitly false;
- CLI `auth confirm --i-confirm-operator-login` writes a non-secret
  `session.json` marker with `status=present`;
- CLI `auth clear` removes the marker without deleting `hh-profile`;
- `auth status` sets `login_ready=true` only when marker is `present` and
  Chromium is installed;
- profile lock is held while the foreground browser session runs.

## Non-scope

Automated credential entry, CAPTCHA solving, OAuth token extraction into CLI
JSON, live HH apply POST, and publishing noVNC beyond loopback.
