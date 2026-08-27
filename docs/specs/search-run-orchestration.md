# SearchRun orchestration (R2.2.4 + R2.2.5 resume_suitable)

## User Story

```text
Как оператор / Web,
Я хочу запустить bounded vacancy acquisition через HH
(primary: подходящие к активному резюме; secondary: SearchProfile),
Чтобы один SearchRun прошёл acquire → detail → Core ingest → SearchRunItem → finalize.
```

## Ownership

- **HH** owns orchestration and browser acquisition transport.
- **Core** owns SearchProfile / SearchRun / SearchRunItem persistence and Vacancy ingest/upsert.
- Browser extractors do **not** write Core.

```text
HH HTTP/CLI
  → run_resume_suitable_search  OR  run_vacancy_search
      → CoreClient (start run with acquisition_kind)
      → acquire_vacancies (page_url_builder + optional serp_guard)
      → vacancy_detail_to_ingest mapper
      → Core ingest + SearchRunItem
      → Core finalize (counters + optional source_total)
```

## HTTP

### Primary — resume suitable (R2.2.5)

`POST /api/v1/vacancies/suitable`

```json
{ "execution": { "order": "publication_time", "max_pages": 1 } }
```

- Active resume from accepted HH context (never hardcoded).
- SERP URL: `resume=` + `from=resumelist` + `hhtmFromLabel=vacancies_for_resume_button`
  + `hhtmFrom=resume_list` + `order_by` (default `publication_time`).
- Mandatory **SERP guard** before ingest: URL resume id, suitable heading,
  result structure → else `resume_search_page_mismatch` (no ingest, failed run).
- Response includes `source_total` (HH total) separate from processed `found_count`.

### Secondary — profile search (R2.2.4)

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
- Observability via Core `GET /api/v1/search-runs/{id}` and `.../items`.

## CLI

`job-search-hh vacancies search --search-profile-id <id> --max-pages 1`

## Snapshot rule

1. Start SearchRun with `acquisition_kind` + immutable snapshots.
2. Execute acquire **only** from those snapshots / resume URL builder.
3. Profile mutations after start do not affect a running `profile_search` run.

## Semantics

| Situation | SearchRun status |
|---|---|
| Valid empty SERP | `success` |
| Bound completed (`max_pages_reached`) | `success` |
| Detail/ingest item errors after some work | `partial` |
| Page failure after successful page(s) | `partial` |
| First-page / login / CAPTCHA / transport / SERP guard before work | `failed` |

- Within one run, each `source_external_id` is processed once (no 409-as-normal).
- Detail failure → item `outcome=error`, `vacancy_id` null; other items continue.
- Page-level failures do **not** create synthetic SearchRunItems.
- Core recomputes counters on finalize; HH does not invent aggregates.
- Terminal runs are immutable; retry = **new** SearchRun.

## Debt (explicit)

- No stale-`running` reclaim / distributed job queue in this slice.
  A killed process may leave `running`; surface that state honestly via Core API.

## Non-scope

Web CTA polish beyond R2.2.5, Scoring/Ollama, fuzzy dedupe, scheduled search,
manual-search staging import, R2.2.A, R2.3.
