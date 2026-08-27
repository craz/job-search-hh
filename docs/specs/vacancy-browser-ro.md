# Browser RO vacancy acquisition (R2.2.2)

## User Story

```text
Как оператор / следующий SearchRun slice,
Я хочу явно через browser read-only получать HH vacancy summaries + detail,
Чтобы иметь поддерживаемый acquisition transport при official API 403.
```

## Implemented

- Explicit transports: `browser_readonly` (supported) vs `official_http_api` (403 /
  unsupported) — **no silent fallback**.
- CLI: `vacancies acquire --transport browser|official|fixture`.
- List-first SERP via `https://hh.ru/search/vacancy?...`, then detail
  `https://hh.ru/vacancy/{id}`.
- Provider DTOs: `HhVacancySummary` / `HhVacancyDetail` (not Core Vacancy).
- Criteria mapping verified on live Web URL; unsupported fields reported.
- Execution policy: `order` → `order_by`, `max_pages`; `page_size` unsupported on Web.
- Pagination progress for later R2.2.4 (`exhausted`, `max_pages_reached`, page fail).
- Recovery: login / CAPTCHA / profile_locked / forbidden — never empty success.
- No HH writes; no Core ingestion.

## Non-scope

Web CTA, Scoring, CAPTCHA bypass, private HH endpoints from browser traffic.
SearchRun orchestration is covered in `search-run-orchestration.md` (R2.2.4).
