# Active goals

STO is becoming its own scheduler: import from a CMMS, Primavera P6 or Microsoft
Project; track, manage and schedule in real time; export back to any of them.
`AGENTS.md` holds the boundaries, `docs/adr/` the decisions, and
`docs/history/` how each decision was reached, and
`docs/roadmap/CONSOLIDATION-PLAN.md` the full design behind the summary below —
the engine slices, field-mapping tables, CMMS mapping-profile schema, round-trip
matrix and phase gates.

Work is sequenced so that each slice ends with something demonstrable. Phases do
not start until the previous gate passes.

## Done

**Monorepo restructure.** `sto_scheduler_core` moved wholesale to `sto.legacy`
(every internal import was relative, so the move cost nothing) and keeps working
as the reference oracle. The unwired duplicate front-end `workspace_web/` is
deleted — it targeted an API that does not exist and was merged alongside the
live UI without ever being connected.

**Canonical model v1 (`sto-canonical-1.0`).** Typed entities, durable UUIDv5
identity with GUID and business-key reconciliation, a reflective codec, and
canonical hashing that refuses floats. Proven on both real BOILER snapshots:
round-trips exactly, two imports of one file hash identically, and 447
activities shared between the snapshots keep their identifiers while 18 new and
13 departed rows are reported rather than conflated. `sto canonicalise` and
`sto reconcile` expose it.

## Now: finish Phase 0, then the engine spine

1. **Assignment identity by business key.** `sto reconcile` over the two BOILER
   snapshots gives assignments 341 matched against 136 new and 131 missing,
   because Microsoft Project renumbers assignment UIDs — the progress field
   contract observed the same thing when it noted resource UIDs and GUIDs were
   renumbered between the before and after files. Key assignments on
   `(task UID, resource UID)`. `IdentityMap` already takes a business key.
2. **Persistence and multi-project.** PostgreSQL, schedule versions with a
   movable head, FastAPI on 8090. Two files import into two projects and survive
   a restart with identical hashes.
3. **Real authentication.** Password with TOTP, server sessions, device tokens
   for the field app. No route accepts a trusted actor header.

Then the engine, in order: calendars compiled with exceptions applied; forward
pass over all four relationship types with signed lag; backward pass, float and
criticality; status date and progress; WBS rollup, the eligibility re-partition
and an independent validator.

## Next: the rest of the roadmap

Live execution loop (progress reaches the live schedule in under a second, the
approved forecast only through review); export with the proven Microsoft Project
transaction and a bound evidence register; CMMS work orders through a mapped-file
adapter and then named SAP PM, Maximo and Oracle EAM adapters; resource
levelling; operational constraints; cut-over.

## Standing constraints

The engine's claims are bounded by the conformance suite and the file oracle.
No writer claims `native-evidence-derived` without an entry in `docs/evidence/`
for that target system and application build. Real customer schedules stay
outside the repository. `Shutdown-Tracker-Claude` stays deployed and untouched
until the parity checklist passes.

## Known gaps recorded, not hidden

- **Assignment identity** as above.
- **Lag calendar for Microsoft files** is an assumption: `ProjectSettings`
  records `lag_calendar_policy = successor` because Microsoft Project exposes no
  such setting. It is written down so it can be falsified by a file with a
  positive working-day lag; BOILER has only zero and elapsed lags.
- **No Primavera file exists anywhere in the estate.** Until one arrives the XER
  and P6 XML paths have no oracle and every P6 writer stays `diagnostic`.
- **`MsSummaryProjection` is populated but nothing writes it back yet**; it
  becomes load-bearing when the MSPDI writer lands.

### Carried from the PR #22 review, against the slice that owns each

Automated review raised 27 findings. The correctness defects are fixed and have
regression tests. These are real but belong to a later slice, and are recorded
here so they are not rediscovered as surprises:

| Gap | Owed to |
|---|---|
| `DurationFormat` is preserved by the importer only as a vendor extension, so `Duration.unit` and `source_format_code` are always empty. The field exists precisely to stop an imported `8h` being written back as `1d`. | S8, MSPDI writer |
| `Assignment.timephased_ref` is never populated, so resource curves and exports cannot find the retained source payload. | S8 |
| `ProjectSettings.critical_float_threshold_seconds` stays zero even when the file sets `CriticalSlackLimit`. | S4, criticality |
| Calendar exceptions are flattened to one continuous `from`/`to`; `entered_by_occurrences` and `occurrences` are dropped, and a missing date becomes `datetime.min`. | S2, where exceptions are first applied |
| `is_null_source` is dropped, so a null placeholder task looks ordinary. | S6, eligibility |
| An unresolved task `CalendarUID` becomes `None`, indistinguishable from inheriting the project calendar. | S2/S3 |
| Summary-task constraints, deadlines, calendars, priority and custom fields are not retained on `WbsNode`. | S8, writeback |
| `effort_driven` reads a key the importer never sets, so it is always `False`. | needs an importer change first |
| Activity business keys (Work Order / Operation) are not passed to `IdentityMap.resolve`, so the documented fallback never fires. | the assignment-identity item above |
| `schedule_id` is re-derived from the file hash when a project has no GUID, even when an `IdentityMap` was supplied. | edge case; no such file yet |
| Fractional durations (`PT0.5S`) truncate to zero rather than failing. | no real file exercises it |
| `scripts/compare_calculation_profiles.py` imports `sto.legacy`, which pre-consolidation checkouts do not have. | research script |

**Not taken.** Rejecting NFC-equivalent duplicate keys at the hashing boundary,
a full strict-primitive regime in the codec (the boolean coercion, which could
invert an activity's meaning, is fixed), and rejecting duplicate GUIDs within
one import. Each adds a way for a real file to stop importing in exchange for a
case none of our files produce. Recorded rather than built.

## Validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

The BOILER cases skip unless the real schedules are present; point
`STO_BOILER_BEFORE` and `STO_BOILER_DAY5` at them to run the file oracle.
`fixtures/README.md` records every file's hash, what it proves and how to
recover it — including two that cannot be recovered and need backing up.
