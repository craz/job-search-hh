# HH application sync (read-only)

## User Story

```text
Как оператор системы поиска работы,
Я хочу синхронизировать уже существующие отклики HeadHunter в Core,
Чтобы видеть факты воронки без отправки новых откликов на HH.
```

## Implemented

- fixture transport for synthetic HH negotiations/applications;
- live authenticated GET `/negotiations` when `--fixture` is omitted (requires
  `login_ready` + access token; see [live-authenticated-read.md](live-authenticated-read.md));
- resolve Core Vacancy by `(source=hh, external_id)` (create from embedded
  vacancy payload when missing);
- normalization to Core `ApplicationCreate` with stable `source=hh`;
- idempotent Core write via `POST /api/v1/applications`;
- versioned JSON CLI `applications sync [--fixture]`;
- capabilities keep `external_writes_enabled=false` (no HH apply).

Repeated sync of the same HH application identity does not create duplicates.

## Non-scope

OAuth token acquisition UI, cookie→API bridging, limited apply live POST and
chats. Planned HH submit simulation lives in [apply-dry-run.md](apply-dry-run.md).
