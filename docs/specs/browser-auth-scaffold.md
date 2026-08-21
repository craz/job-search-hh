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
  are present;
- operator login commands live in [operator-novnc-login.md](operator-novnc-login.md).

## Non-scope

Automated credential entry, CAPTCHA solving, live apply POST and exposing noVNC
beyond loopback.
