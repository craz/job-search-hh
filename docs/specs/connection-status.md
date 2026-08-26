# HH connection status (R1.1)

## User Story

```text
Как оператор,
Я хочу видеть актуальное состояние подключения HeadHunter,
Чтобы знать, можно ли использовать authenticated HH context.
```

## Implemented

- Product contract statuses: `connected`, `not_authorized`, `expired`,
  `action_required`, `unavailable`
- CLI: `job-search-hh connection status`
- HTTP: `GET /api/v1/connection` (+ open-login / confirm actions)
- Mapping reuses existing auth/session/token markers; no second auth system
- Secrets never appear in envelopes
- Connected does **not** claim `/me`, `/resumes/mine`, or negotiations access
- Additive `recovery` taxonomy (R1.6): see [`recovery-states.md`](recovery-states.md)

## Non-scope

Account/profile fetch (R1.2), resume list (R1.3), active resume, CandidateProfile.
