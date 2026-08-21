# HH resume-view enriched metrics

## User Story

```text
Как оператор системы поиска работы,
Я хочу видеть views_total/views_new из моих резюме в дневных метриках,
Чтобы воронка учитывала просмотры, а не только negotiations counters.
```

## Implemented

- Authenticated live `metrics sync` calls GET `/resumes/mine` and sums
  `views_count` / `new_views_count` (with counters fallbacks);
- merges those fields into the same daily snapshot as negotiations-derived
  applications/replies/invitations/rejections;
- HTTP 403 on resumes does not fail the sync (negotiations-only fallback);
- never POSTs to HH.

## Non-scope

HTML/browser history scrape of `/applicant/resumes` view charts and multi-day
series backfill.
