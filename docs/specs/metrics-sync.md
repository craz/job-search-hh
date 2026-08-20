# HH daily metrics sync (read-only)

## User Story

```text
Как оператор системы поиска работы,
Я хочу переносить дневные метрики воронки в Core,
Чтобы видеть динамику просмотров и откликов без записи на HH.
```

## Implemented

- fixture transport for synthetic daily metric snapshots;
- normalization to Core `DailyMetricUpdate` fields;
- idempotent Core write via `PUT /api/v1/metrics/{metric_date}`;
- versioned JSON CLI `metrics sync --fixture`;
- capabilities keep `external_writes_enabled=false`.

Identical snapshot replay under the same fingerprint key does not conflict.
Changed counts use a new fingerprint key and update the same calendar date.

## Non-scope

Live authenticated HH stats APIs, browser/profile collection, apply and
negotiations live sync remain out of this slice.
