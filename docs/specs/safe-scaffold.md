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
- unit, contract and executable pytest-bdd checks;
- reproducible local/CI interfaces and minimal diagnostic Dockerfile.

## Non-scope

HH OAuth/API, Chromium, Playwright, noVNC, persistent profile, Core sync and all
apply operations are not implemented in this scaffold. Their dependencies and
runtime artifacts must be introduced and verified in dedicated vertical slices.

