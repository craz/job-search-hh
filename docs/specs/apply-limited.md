# HH limited apply scaffold

## User Story

```text
Как оператор системы поиска работы,
Я хочу иметь gated limited-apply команду,
Чтобы случайный запуск не отправил отклик на HH без явного разрешения.
```

## Implemented

- CLI `apply limited --fixture` with mandatory `--i-authorize-hh-writes`;
- runtime gate `JOB_SEARCH_HH_EXTERNAL_WRITES_ENABLED=true` (default false);
- per-run limit (`--limit`, default 1) and declared `captcha_stop=true` policy;
- refusal report when either gate is missing (`external_writes_disabled` /
  `authorization_required`) with `hh_write_attempted=false`;
- when both gates pass, scaffold still does **not** open HH write HTTP — items are
  marked `gated_ready` / `execution=not_implemented` until a dedicated live
  transport slice exists;
- capabilities package default remains `external_writes_enabled=false`.

## Non-scope

Real HH negotiation POST, CAPTCHA solving, browser/auth session, OAuth token
use and Core Application create from limited apply remain out of this scaffold.
