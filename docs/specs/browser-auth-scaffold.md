# HH browser/auth runtime

## User Story

```text
Как оператор системы поиска работы,
Я хочу Chromium/Playwright/noVNC внутри HH container с persistent profile,
Чтобы войти через loopback noVNC, не публикуя VNC наружу.
```

## Implemented

- Docker image installs Playwright Chromium plus Xvfb/x11vnc/noVNC/websockify;
- runtime script starts virtual display and loopback-facing noVNC;
- Compose publishes noVNC only on `127.0.0.1:6080`;
- volumes `hh-profile` / `hh-state` remain HH-owned;
- `session status` reports `browser_automation=installed` when Chromium+noVNC
  are present; `auth status` stays `login_ready=false` until a login slice;
- capabilities never enable `external_writes_enabled`.

## Non-scope

Automated HH login, OAuth token capture, CAPTCHA handling, live apply POST and
exposing noVNC beyond loopback.
