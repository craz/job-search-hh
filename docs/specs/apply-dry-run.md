# HH apply dry-run

## User Story

```text
Как оператор системы поиска работы,
Я хочу прогнать план отклика в dry-run,
Чтобы увидеть, что ушло бы на HH, не отправляя отклик.
```

## Implemented

- versioned JSON CLI `apply dry-run --fixture`;
- plan normalization for vacancy/resume/message metadata;
- `FakeApplyTransport` that records `would_send` audit and never performs HH writes;
- report fields `mode=dry-run`, `hh_write_attempted=false`, `external_writes_enabled=false`;
- no Core Application create from this path (local facts stay Web/sync).

## Non-scope

Live HH submit, limited apply, CAPTCHA handling, browser/Playwright/noVNC,
OAuth and tick/autopilot remain out of this slice.
