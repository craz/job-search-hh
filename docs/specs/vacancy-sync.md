# HH vacancy sync (read-only)

## User Story

```text
Как оператор системы поиска работы,
Я хочу читать публичные вакансии HeadHunter и сохранять их в Core,
Чтобы наполнять воронку без отправки откликов и без доступа к PostgreSQL Core.
```

## Implemented

- provider-neutral HH vacancy fetch (HTTP client + fixture transport for tests);
- normalization to Core `VacancyCreate` with stable `source=hh`;
- idempotent Core write via `POST /api/v1/vacancies` and `Idempotency-Key`;
- versioned JSON CLI `vacancies sync`;
- capabilities report `hh_api=read-only` with `external_writes_enabled=false`.

Repeated sync of the same HH vacancy identity does not create duplicates in Core.

## Non-scope

OAuth login, Chromium/Playwright/noVNC, persistent browser profile, apply/dry-run,
negotiations, chats, metrics sync and any HH write are out of this slice.
