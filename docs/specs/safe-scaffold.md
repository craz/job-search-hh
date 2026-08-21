# Safe HH scaffold

## User Story

```text
Как оператор системы поиска работы,
Я хочу видеть фактически настроенные возможности HH-интеграции,
Чтобы незавершённый компонент не выполнял внешние действия.
```

## Implemented

- Python package and versioned JSON capabilities CLI;
- explicit `external_writes_enabled=false` safety default;
- `hh_api=read-only` once vacancy sync is available;
- `browser_automation=scaffold` once profile/state paths exist without Chromium;
- unit, contract and executable pytest-bdd checks;
- reproducible local/CI interfaces and minimal diagnostic Dockerfile.

## Non-scope

OAuth, Chromium, Playwright, noVNC, persistent profile and all apply operations
remain out of the scaffold. Vacancy read/sync is covered by
[vacancy-sync.md](vacancy-sync.md).
