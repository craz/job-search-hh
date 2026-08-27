# SearchRun orchestration (R2.2.4)

## User Story

```text
Как оператор / Web (R2.2.5),
Я хочу запустить bounded vacancy search от persisted SearchProfile через HH,
Чтобы один SearchRun прошёл acquire → detail → Core ingest → SearchRunItem → finalize.
```

## Ownership

- **HH** owns orchestration and browser acquisition transport.
- **Core** owns SearchProfile / SearchRun / SearchRunItem persistence and Vacancy ingest/upsert.
- Browser extractors do **not** write Core.

```text
HH HTTP/CLI
  → search_run_orchestration.run_vacancy_search
      → CoreClient (profile + start run)
      → VacancyProvider / acquire_vacancies (immutable snapshots)
      → vacancy_detail_to_ingest mapper
      → Core ingest + SearchRunItem
      → Core finalize (counters recomputed from items)
```

## HTTP

`POST /api/v1/vacancies/search`

```json
{
  "search_profile_id": "<uuid>",
  "execution": {
    "order": "publication_time",
    "max_pages": 1
  }
}
```

- `page_size` is **rejected** (unsupported Web browser knob).
- Response includes `search_run`, `acquisition`, `items`, terminal `status`.
- Observability of snapshots/counters/items also via Core
  `GET /api/v1/search-runs/{id}` and `.../items`.

## CLI

`job-search-hh vacancies search --search-profile-id <id> --max-pages 1`

## Snapshot rule

1. Read SearchProfile once.
2. `POST` SearchRun with `criteria_snapshot` + `execution_snapshot` (`transport=browser`).
3. Execute acquire **only** from those immutable snapshots.
4. Profile mutations after start do not affect the running SearchRun.

## Semantics

| Situation | SearchRun status |
|---|---|
| Valid empty SERP | `success` |
| Bound completed (`max_pages_reached`) | `success` |
| Detail/ingest item errors after some work | `partial` |
| Page failure after successful page(s) | `partial` |
| First-page / login / CAPTCHA / transport before work | `failed` |

- Within one run, each `source_external_id` is processed once (no 409-as-normal).
- Detail failure → item `outcome=error`, `vacancy_id` null; other items continue.
- Page-level failures do **not** create synthetic SearchRunItems.
- Core recomputes counters on finalize; HH does not invent aggregates.
- Terminal runs are immutable; retry = **new** SearchRun.

## Debt (explicit)

- No stale-`running` reclaim / distributed job queue in this slice.
  A killed process may leave `running`; surface that state honestly via Core API.

## Non-scope

Web CTA/editor, Scoring/Ollama, fuzzy dedupe, scheduled search, R2.2.5, R2.3.
