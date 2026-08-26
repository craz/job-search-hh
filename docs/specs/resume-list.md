# HH own-resume list + active selection (R1.3 / R1.4)

## User Story

```text
Как оператор,
Я хочу получить список своих HH resumes и выбрать одно активное
(или явно none),
Чтобы знать, каким резюме я сейчас пользуюсь в Job Search.
```

## Implemented

### List (R1.3)

- Transport: authenticated **browser** session, **read-only** navigation to
  `https://hh.ru/applicant/resumes` (official `GET /resumes/mine` remains blocked).
- CLI: `job-search-hh resumes list`
- HTTP: `GET /api/v1/resumes`
- Normalized items: `external_id`, `title`, `active`
- Statuses: `available` (incl. empty), `not_authorized`, `permission_blocked`,
  `unavailable`
- Login wall / missing browser session → **not** an empty successful list
- Web maps `action.open_login` / `confirm_login` to product buttons
  («Войти в HeadHunter» / «Я вошёл — показать резюме»)
- Never dumps cookies, tokens, or raw HTML

### Active selection (R1.4)

- Source of truth: HH state file `active_resume.json` under `HH_STATE_DIR`
  (survives process/container restart; **not** Core CandidateProfile — R1.5).
- Exactly one of: one active resume, or explicit **none**. No auto-select when
  the list has a single item.
- CLI: `job-search-hh resumes select --id <external_id>`, `resumes clear`
- HTTP: `PUT /api/v1/resumes/active` body `{"external_id": "<id>" | null}`
- List payload includes:
  - `items[].active`
  - `active_resume`: `{external_id, title} | null`
  - `selection.status`: `none` | `active` | `stale` | `unavailable`
- Select rejected if id not in current available list (`invalid_resume_id`).
- Select rejected when list not available (`selection_unavailable`).
- Stale: stored id missing from current list → `selection.status=stale`,
  `active_resume=null`, action `reselect` (not silent fake success).
- When list unavailable: selection UI inoperable; stored id may appear under
  `selection.external_id` but is not presented as current active resume.

## Non-scope

Core CandidateProfile / ProfileVersion linkage (R1.5), resume editing, browser
apply, CAPTCHA bypass, official API resume list, SearchProfile.
