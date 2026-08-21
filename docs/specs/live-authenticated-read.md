# HH live authenticated read (negotiations / derived metrics)

## User Story

```text
Как оператор системы поиска работы,
Я хочу читать существующие переговоры HH через API после confirmed session,
Чтобы синхронизировать воронку в Core без записи на HH.
```

## Implemented

- CLI `applications sync` without `--fixture` uses Bearer GET `/negotiations`;
- CLI `metrics sync` without `--fixture` derives one UTC daily snapshot from the
  same negotiations GET (`notes=derived_from_negotiations_get`);
- dual gate: `auth status` must be `login_ready` and access token must exist via
  `JOB_SEARCH_HH_ACCESS_TOKEN` or `HH_STATE_DIR/access_token` (never printed);
- reports include `transport=authenticated_api` and `hh_write_attempted=false`;
- fixture path remains available offline.

## Non-scope

Cookie→API bridging, resume-view history scrape, POST `/negotiations`, limited
apply live transport and CAPTCHA bypass. OAuth URL/exchange/storage lives in
[oauth-token-store.md](oauth-token-store.md).
