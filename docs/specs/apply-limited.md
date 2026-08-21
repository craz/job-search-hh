# HH limited apply (gated live transport)

## User Story

```text
Как оператор системы поиска работы,
Я хочу dual-gated limited apply с реальным POST /negotiations,
Чтобы отклик ушёл на HH только после явного разрешения и без CAPTCHA bypass.
```

## Implemented

- CLI `apply limited --fixture --i-authorize-hh-writes` plus
  `JOB_SEARCH_HH_EXTERNAL_WRITES_ENABLED=true`;
- when both gates pass, CLI also requires `login_ready` + access token and uses
  `HttpApplyTransport` to POST form data to `/negotiations`;
- per-run `--limit` (default 1); `captcha_stop=true` — HTTP 403/429/captcha body
  stops the run (`execution=stopped_captcha`);
- refusal without gates (`external_writes_disabled` / `authorization_required` /
  `transport_required` / `login_not_ready` / `access_token_missing`) keeps
  `hh_write_attempted=false`;
- capabilities package default remains `external_writes_enabled=false`.

## Non-scope

CAPTCHA solving, automatic Core Application create from apply results, chats and
unattended multi-apply without the dual gate.
