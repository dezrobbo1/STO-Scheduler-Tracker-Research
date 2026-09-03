# Native evidence register

A writer may claim `native-evidence-derived` only when this directory holds an
entry for the target system **and the application build**. A transaction proven
against one Microsoft Project build is not proven against another, so the build
number is part of the key, not a footnote.

Real schedules and generated artifacts stay outside git. Record hashes,
sanitized structural findings, and the decision.

Every new target or build needs a **control run** first: put an untouched source
through the target application, save, and re-import. Whatever moves is that
build's own normalisation, and it is the baseline every later comparison is read
against. Without it, the target's own behaviour is misread as a defect in ours —
on BOILER, Microsoft Project moved ten unrelated multi-assignment tasks and
collapsed 2,202 timephased rows to 462 with no input from us at all.

## Layout

```
docs/evidence/
  register.json                    machine-readable index (arrives with P8 - PR-evidence-register)
  microsoft-project/<build>/...    per build
  p6/<version>/...
  cmms/<system>/...
  field/                           offline and sync evidence
```

## Carried forward from the frozen repositories

Two Microsoft Project entries exist and are to be ported here with their
provenance:

| Date | Build | Scope | Source |
|---|---|---|---|
| 2026-08-28 | 16.0.20228.20188 | Single completed assigned task, UID 43; no MPP persist cycle; no control run | `Shutdown-Tracker-Claude` |
| 2026-08-30 | 16.0.20228.20186 | 13 tasks including UID 43, XML to MPP to reopen, **with** an untouched-source control | `Shutdown-Tracker` |

The second supersedes and extends the first. Note the two registers used
different builds two days apart, with the later test on the earlier build; the
BOILER day-5 candidate names a third, `16.0.20131.20152`. Reconciling which
build a claim belongs to is part of porting them.
