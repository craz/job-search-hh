# Manual HH → Core resume content sync (R2.1.3 / TECH-US-01.4)

## User Story

```text
Как оператор,
Я хочу вручную синхронизировать содержание активного HH-резюме в Core,
Чтобы появился локальный immutable ResumeVersion для будущего scoring.
```

## Flow

```text
active HH resume (or --id)
  → browser RO allowlist extract (R2.1.2)
  → POST /api/v1/resume-versions (Core)
  → created | unchanged (same content_hash)
  → candidate-context.resume_content metadata
  → GET /api/v1/resume-versions/{id} for full body
```

## Implemented

- CLI: `job-search-hh resumes sync` (default = active selection)
  or `job-search-hh resumes sync --id <external_id>`
- HTTP: `POST /api/v1/resumes/sync` body `{"external_id": "<id>"?}`
- Uses R2.1.2 extractor; transport `browser_readonly`
- Core contract payload:
  `source`, `external_resume_id`, `transport`, `extractor_version`,
  `captured_at`, `content` (allowlisted only)
- Current local copy = active HH link + latest ResumeVersion for
  `(profile_version_id, source, external_resume_id)` — **no** pointer table
- Extract / recovery failure → **no** Core write / no fake ResumeVersion
- Unchanged content → `created=false` / code `unchanged`

## Non-scope

Web sync CTA (R2.1.5), auto-sync on select, vacancy, Scoring, PDF/HTML,
pointer table, version-change demo as a separate product slice.
