# HH account/profile context (R1.2)

## User Story

```text
Как оператор,
Я хочу видеть, к какому HH account сейчас подключён Job Search,
Чтобы подтвердить правильный контекст без сырого /me JSON.
```

## Implemented

- Official API `GET /me` only (no browser transport)
- Normalized product contract: `status`, `account.{external_id,display_name,email}`,
  `connection_status`, `code`, `checked_at`, `action`, `recovery`
- CLI: `job-search-hh account status`
- HTTP: `GET /api/v1/account`
- Connection (R1.1) failures short-circuit without calling `/me`
- Keeps `action_required` distinct from `not_authorized` (R1.6)
- Does **not** treat `counters.resumes_count` as resume-list capability

## Non-scope

Resume list (R1.3), active resume, CandidateProfile, Core schema.
See also [`recovery-states.md`](recovery-states.md).
