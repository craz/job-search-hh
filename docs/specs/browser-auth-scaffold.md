# HH browser/auth scaffold

## User Story

```text
Как оператор системы поиска работы,
Я хочу видеть состояние browser/auth scaffold и persistent paths,
Чтобы понимать, что Chromium ещё не установлен, а profile/state volumes уже
зарезервированы без download браузеров.
```

## Implemented

- CLI `session status` and `auth status` reporting scaffold readiness;
- `HH_STATE_DIR` / `HH_PROFILE_DIR` paths with single-process profile lock stub;
- capabilities `browser_automation=scaffold` (not ready, no Chromium/Playwright/noVNC);
- Compose service `hh` with named volumes `hh-state` and `hh-profile`;
- no Playwright/Chromium package install and no browser download in this slice.

`auth status` reports `absent` until a future login slice writes a synthetic
session marker. Real OAuth/login/noVNC are out of scope.

## Non-scope

Chromium/Playwright binary install, noVNC port publish, interactive login,
session persistence after real HH auth, and live browser automation.
