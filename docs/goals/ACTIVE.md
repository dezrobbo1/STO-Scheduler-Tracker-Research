# Active goals

STO is becoming its own scheduler: import from a CMMS, Primavera P6 or Microsoft
Project; track, manage and schedule in real time; export back to any of them.
`AGENTS.md` holds the boundaries, `docs/adr/` the decisions, and
`docs/history/` how each decision was reached.
`docs/roadmap/CONSOLIDATION-PLAN.md` is the design behind the summary below —
the engine slices, field-mapping tables, CMMS mapping-profile schema and
round-trip matrix — frozen on 2026-09-02 and not maintained. Phases, gates,
effort and what the work waits on are here and in `docs/goals/roadmap.json`.

Work is sequenced so that each slice ends with something demonstrable. Phases do
not start until the previous gate passes.

## Where the plan stands

<!-- roadmap:begin now -->
<!-- generated from docs/goals/roadmap.json by `sto roadmap render`; edit the JSON, not this -->

**P0 — Monorepo and spine model** (in progress; 5 of 6 gate criteria met)

| | Gate criterion | Shown by |
|---|---|---|
| ✓ | The canonical document round-trips exactly on both real BOILER snapshots | `tests/test_canonical_model.py` ‡ |
| ✓ | Two imports of one file hash identically, and a later snapshot keeps the identifiers of every row whose source UID survived | `docs/history/2026-09-02-consolidation-and-canonical-model.md` |
| ✓ | Every row the reconciliation reports as new or missing is attributable to a difference between the source documents, not to identity | `tests/test_canonical_model.py` ‡ |
| · | Two schedules import into two projects and survive a restart with identical hashes | — |
| ✓ | The unittest suite and compileall are green on the declared Python floor | `.github/workflows/ci.yml` |
| ✓ | Every statement in AGENTS.md is either durable or machine-checked | `tests/test_governance_references.py` |

‡ the real BOILER schedules live outside the repository, so this evidence does not execute in CI unless they are present; set `STO_REQUIRE_BOILER=1` to make their absence a failure rather than a skip.

<!-- roadmap:end now -->

## What the work waits on

These are not code. Each names the slices and criteria it gates, so a gate that
cannot be crossed says so now rather than in the week it is reached, and a
criterion a blocked dependency names cannot be marked met.

<!-- roadmap:begin dependencies -->
<!-- generated from docs/goals/roadmap.json by `sto roadmap render`; edit the JSON, not this -->

| Dependency | Status | Gates | Asked |
|---|---|---|---|
| `DEP-P6-FILE` — A real Primavera P6 export (XER or PMXML) from a site, and one P6 session to open what we write | blocked | I5, I13, P3-G3 | — |
| `DEP-CMMS-EXTRACT` — A real CMMS extract - SAP IW37N/IW39, Maximo WOTRACK or Oracle eAM operations - even anonymised | blocked | I11, I12 | — |
| `DEP-PROJECT-SESSION` — A Windows machine running Microsoft Project, for one native session per evidence register entry | available | I13, P3-G5 | — |
| `DEP-SITE-TEMPLATES` — The site's own confirmation-upload template for whichever CMMS is first | blocked | I11 | — |
| `DEP-UNTOUCHED-SOURCE` — The untouched BOILER source e6a3739976580e21 that both evidence lines cite | blocked | I13 | — |
| `DEP-DAY5-BACKUP` — A durable off-machine copy of the day-5 candidate schedule, the only progress oracle | at risk | S5, P1-G2 | — |

<!-- roadmap:end dependencies -->

The first two are asks, not tasks: a Primavera export and a CMMS extract have to
come from a site. Until they do, every P6 writer and every named CMMS adapter
stays `diagnostic` by design rather than by omission.

## Done

**Monorepo restructure.** `sto_scheduler_core` moved wholesale to `sto.legacy`
(every internal import was relative, so the move cost nothing) and keeps working
as the reference oracle. The unwired duplicate front-end workspace_web/ is
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

1. **Explain the reconciliation counts, don't re-key them.** `sto reconcile`
   over the two BOILER snapshots gives assignments 341 matched against 136 new
   and 131 missing. That was first read as Microsoft Project renumbering
   assignment UIDs, calling for a `(task UID, resource UID)` business key.
   Measured, that key matches exactly the rows the UID already matches, on both
   available file pairs — necessarily, because the importer derives both halves
   of it from those UIDs. The split is real churn: of the 131, five are
   unassigned placeholders, thirteen belong to a task that also went, and the
   rest sit on tasks that survived while their resourcing changed. Identity is
   working. What is owed is the guard that keeps it honest, which
   `tests/test_canonical_model.py` now carries.
2. **Persistence and multi-project.** PostgreSQL, schedule versions with a
   movable head, FastAPI on 8090. Two files import into two projects and survive
   a restart with identical hashes. Versions, heads and the stored document
   only: the per-activity projection of early and late dates, float and
   criticality waits for the passes that give those columns a meaning (ADR-006).
   Third-party packages arrive here, behind the `api` extra — the base package,
   the suite and CI stay stdlib-only (ADR-005).
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
adapter and then named SAP PM, Maximo and Oracle EAM adapters; then **cut-over**,
then resource levelling and operational constraints.

Cut-over comes before the levelling work, not after it. What the parity
checklist asks for is problems and critical updates, not levelling, so putting
levelling first would leave `Shutdown-Tracker-Claude` deployed and unmaintained
for the length of a slice it does not need (ADR-004). The differentiators are
then built against a stack in use.

Effort is recorded per slice in `docs/goals/roadmap.json` and totalled by
`sto roadmap status`, so no document has to carry a number that goes stale. Read
those totals as slice work only: review, rework and the manual native sessions
are on top, and the phases at the front of the list are the ones whose estimates
have never been tested.

## Rules stated but not yet enforceable

`AGENTS.md` states some rules before the machinery exists to check them; each
carries an id and a condition. When the condition is met the suite fails and
asks for the rule to be promoted, so none of this depends on anyone remembering.

<!-- roadmap:begin rules -->
<!-- generated from docs/goals/roadmap.json by `sto roadmap render`; edit the JSON, not this -->

| Rule | Owed to | Status | Enforced by / goes live when |
|---|---|---|---|
| `PR-core-stdlib-only` | S1 | live | `tests/test_core_is_stdlib_only.py` |
| `PR-no-schedule-content` | S1 | live | `tests/test_docs_carry_no_schedule_content.py` |
| `PR-conformance-suite` | S3 | pending | src/sto/conformance exists |
| `PR-evidence-register` | I13 | pending | docs/evidence/register.json exists |
| `PR-approved-forecast` | PL6 | pending | sto.execution.review imports |
| `PR-migrations` | PL1 | pending | infra/migrations exists |
| `PR-legacy-retirement` | I4 | pending | src/sto/interchange exists |

<!-- roadmap:end rules -->

## Standing constraints

The engine's claims are bounded by the conformance suite and the file oracle.
No writer claims `native-evidence-derived` without an entry in `docs/evidence/`
for that target system and application build. Real customer schedules stay
outside the repository. `Shutdown-Tracker-Claude` stays deployed and untouched
until the parity checklist passes.

## Known gaps recorded, not hidden

- **GUID is not a durable key on this site's Microsoft Project export path.**
  Between the two BOILER snapshots every shared task UID kept its work-order and
  operation key and carried a regenerated GUID, so the GUID rekey fallback in
  `IdentityMap` cannot fire on that path and a rule treating a changed GUID as
  a different row matches nothing (ADR-002, second amendment). Other builds and
  export routes are unmeasured, so the fallback stays. Reconciliation now
  counts matched rows whose GUID moved, which is how the next path gets
  measured. The fallback that does hold here is the work-order and operation
  pair — see the business-key gap below.
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
`STO_BOILER_BEFORE` and `STO_BOILER_DAY5` at them to run the file oracle. Two
gate criteria rest on those cases, so cross a gate with `STO_REQUIRE_BOILER=1`
set — their absence then fails instead of skipping quietly.
`fixtures/README.md` records every file's hash, what it proves and how to
recover it — including two that cannot be recovered and need backing up.
