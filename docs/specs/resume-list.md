# HH own-resume list (R1.3)

## User Story

```text
Как оператор,
Я хочу получить список своих HH resumes,
Чтобы выбрать, с каким резюме работать дальше.
```

## Implemented

- Transport: authenticated **browser** session, **read-only** navigation to
  `https://hh.ru/applicant/resumes` (official `GET /resumes/mine` remains blocked).
- CLI: `job-search-hh resumes list`
- HTTP: `GET /api/v1/resumes`
- Normalized items: `external_id`, `title` only
- Statuses: `available` (incl. empty), `not_authorized`, `permission_blocked`,
  `unavailable`
- Login wall / missing browser session → **not** an empty successful list
- Web maps `action.open_login` / `confirm_login` to product buttons
  («Войти в HeadHunter» / «Я вошёл — показать резюме»)
- Never dumps cookies, tokens, or raw HTML

## Non-scope

Active resume select (R1.4), resume editing, browser apply, CAPTCHA bypass,
official API resume list, Core CandidateProfile.
