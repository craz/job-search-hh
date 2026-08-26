# HH recovery / action-required (R1.6 / US-00.6)

## User Story

```text
Как оператор,
Я хочу явно видеть not authorized / expired / CAPTCHA / permission denied,
Чтобы не путать внешний блок с «пустым списком» или молчаливым сбоем.
```

## Implemented

Additive `recovery` object on connection / account / resumes envelopes:

| `recovery.kind` | Meaning | Typical sources |
|---|---|---|
| `none` | Ready / no operator recovery | `connected` / `available` |
| `reauth` | Re-login / reconnect | `not_authorized`, `expired`, 401 |
| `captcha_or_action_required` | CAPTCHA or operator confirm; no bypass | browser captcha page, pending confirm |
| `external_limitation` | HH scope / permission limit | 403, permission_blocked |
| `network_failure` | Transient transport failure | upstream / browser read failures |

Also:

- Account keeps `action_required` distinct from `not_authorized`
- Resumes browser extract detects CAPTCHA selectors → `action_required`
- Web shows distinguishable copy + bounded polls only (no silent retry storm)
- CAPTCHA is never bypassed

## Non-scope

R1.A Gate evidence pack, resume content ingestion, silent auto-reauth loops,
permanent product chrome beyond acceptance/debug visibility for linkage.
