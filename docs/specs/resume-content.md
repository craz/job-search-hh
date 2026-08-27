# HH own-resume detail content extract (R2.1.2 / TECH-US-01.3)

## User Story

```text
Как оператор,
Я хочу извлечь allowlisted содержание своего HH-резюме read-only браузером,
Чтобы позже (R2.1.3) сохранить его как локальный ResumeVersion без контактов.
```

## Implemented

- Transport: authenticated **browser** session, **read-only** navigation to
  `https://hh.ru/resume/{external_id}` (same Chromium profile / `ProfileLock` /
  recovery as the resume list).
- CLI: `job-search-hh resumes content --id <external_id>`
- HTTP: `GET /api/v1/resumes/{external_id}/content`
- Allowlist fields (when present on the owner page):
  `title`, `desired_position`, `about`, `skills`, `experience`, `education`,
  `languages`, `salary`, `location`, `employment_preferences`
- Envelope includes: `status`, `code`, `recovery`, `action`,
  `external_resume_id`, `source=hh`, `transport=browser_readonly`,
  `extractor_version`, `captured_at`, `content`
- Statuses: `available`, `not_authorized`, `permission_blocked`,
  `action_required`, `unavailable`
- Login wall / locked profile / captcha → **not** fake empty success
- Defense-in-depth PII scrub on extracted text (email/phone patterns)
- Never dumps cookies, tokens, raw HTML, or contact blocks
- **Does not** write to Core (manual HH→Core sync is R2.1.3)

## Non-scope

Core ingest / ResumeVersion write (R2.1.3), Web sync CTA (R2.1.5), vacancy,
scoring, PDF/HTML artifacts, auto-sync on select, official HH resume API.
