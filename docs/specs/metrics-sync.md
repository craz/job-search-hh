# HH daily metrics sync (read-only)

## User Story

```text
Как оператор системы поиска работы,
Я хочу переносить дневные метрики воронки в Core,
Чтобы видеть динамику просмотров и откликов без записи на HH.
```

## Implemented

- fixture transport for synthetic daily metric snapshots;
- live path without `--fixture` builds one UTC daily snapshot from authenticated
  GET `/negotiations` plus GET `/resumes/mine` view counters
  (`notes=negotiations_get+resumes_mine`); resume-scope HTTP 403 falls back to
  negotiations-only (`…+resumes_mine_forbidden`);
- normalization to Core `DailyMetricUpdate` fields;
- idempotent Core write via `PUT /api/v1/metrics/{metric_date}`;
- versioned JSON CLI `metrics sync [--fixture]`;
- capabilities keep `external_writes_enabled=false`.

Identical snapshot replay under the same fingerprint key does not conflict.
Changed counts use a new fingerprint key and update the same calendar date.

## Non-scope

Browser scrape of resume-view history charts, per-day historical series import,
apply and HH write endpoints.
