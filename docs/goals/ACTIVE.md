# Active goals

STO is becoming its own scheduler: import from a CMMS, Primavera P6 or Microsoft
Project; track, manage and schedule in real time; export back to any of them.
Today it imports Microsoft Project XML, calculates it, and stores it; the
rest is the roadmap below, and the 2026-09-07 comprehensive repository review
(`docs/history/2026-09-08-review-answered-and-roadmap-resequenced.md`) is
the honest statement of the distance.
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

**P1 — Engine and local planner trial** (in progress; 1 of 5 gate criteria met)

| | Gate criterion | Shown by |
|---|---|---|
| ✓ | The 47 executable conformance cases pass, byte-identically across three processes | `tests/test_conformance_determinism.py` |
| · | Both BOILER snapshots: every leaf activity gets a disposition, and no difference is UNEXPLAINED across start, finish, late dates, float and criticality | — |
| · | The genuine Project-recalculation oracle (before to after-native-progress) reports zero unexpected differences | — |
| · | A persisted import shows calculated dates beside the ones it imported; one duration edit moves its successors; reset restores the baseline; the scenario exports; and a restart reproduces the same result from the same input hash | — |
| · | Every API route rejects an unauthenticated request, and a project is readable only by an actor authorised on it | — |

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
| `DEP-UNTOUCHED-SOURCE` — The untouched BOILER source e6a3739976580e21 that both evidence lines cite | available | I13 | 2026-09-03 |
| `DEP-DAY5-BACKUP` — A durable off-machine copy of the day-5 candidate schedule, the only file carrying an activity that has started and not finished | at risk | S5, P1-G2 | — |

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

**The calculated schedule, visible (PL13).** A stored import can be calculated
through the API and read back as a page: every activity with the dates the file
carried beside the dates the engine computed, what placed each row, its floats,
its progress state, and for an excluded row the code that says why there are no
dates. The summaries show their rolled-up spans, and a branch with nothing
beneath it is shown as a branch with no span rather than omitted. Reading goes
through the verified loader, which reassembles the result from the header and
both row sets and refuses a fingerprint that no longer matches its rows, so an
edited row is a refusal rather than an answer. A restart serves the same
calculation from the same stored input.

**The calculated result (PL3).** `sto.core.engine.result` assembles one row per
activity out of the passes, the float, the rollup and the plan's dispositions,
and derives nothing a second time. A scheduled row carries four dates, two
floats, its progress state and what placed it; an excluded row carries the code
that says why and no dates at all. Schedule dates are stored as wall-clock
without a time zone, because a Microsoft Project date carries no offset and
attaching one would move the working day. `Workspace.calculate` runs the engine
over a project's stored head and stores the answer, reading the document back
through the hash check so nothing is computed over bytes that do not hash to
what they claim.

**Persistence and multi-project (PL1).** PostgreSQL on the existing loopback
instance, a new `sto` database, and `V001`: projects, source files,
import batches, and the schedule-version envelope — immutable versions with
the full canonical document and identity map, a movable head per kind
(ADR-007). FastAPI over it: create projects, upload a schedule, read the head.
The working model is rebuilt from heads at boot and every load recomputes the
document's hash from what PostgreSQL returns; a version that does not hash to
what it says is reported by health and refused, not served. The gate — two
schedules, two projects, a restart, identical hashes — is held by
`tests/test_persistence_gate.py` on synthetic files in CI and on the BOILER pair
here, where the recorded reconciliation counts come through the database
unchanged. Third-party packages arrived behind the `api` extra; the bare suite
and CI job stay stdlib-only (ADR-005). `sto serve` runs it on 8092 — 8090 is
the deployed Java API until cut-over.

**Calendars (S2).** `sto.core.calendar` compiles a canonical calendar — base
inheritance, weekday overrides, dated exceptions with their recurrence, and
the legacy special days the migration now carries as exceptions — into sorted
integer working intervals over a horizon, with a fingerprint. The reference
arithmetic from the conformance corpus's implementation is kept verbatim; an
indexed layer answers the engine's questions in O(log n) and is held to the
reference on ten thousand random inputs per function, and to the previous
engine on ten thousand (moment, duration) pairs across every real BOILER
calendar. All forty-five compile. Every one of their exception days falls
outside the 2026 schedule window — the calendars came from a 2024–25
template — so the exception test compiles over 2025 to exercise them. Six of
the corpus's ten calendar cases pass on the arithmetic alone; the four with
relationships belong to the forward pass.

**Forward pass (S3).** `sto.core.engine` takes integer coordinates and compiled
intervals, never a schedule, so the corpus — declared in hours — drives the
real engine rather than a copy of it. All four relationship types with signed
lag; zero lag does not snap because placement already does; milestones read
`MilestoneSnapPolicy` instead of picking. Every corpus case a forward pass
alone can answer passes exactly. The corpus itself is now in the package,
`src/sto/conformance/`, byte-pinned to the commit its manifest names and
hash-checked on every read, so it runs in CI with nothing to set. Against the
dates Microsoft Project stored in the BOILER file the pass first agreed on one
activity, recorded undiagnosed in `docs/history/2026-09-03-forward-pass.md`;
the diagnosis (`docs/history/2026-09-05-forward-pass-residue-diagnosed.md`,
ADR-010) found four rules of Project's — the resource calendar places the
work, the task or project calendar measures lags and slack, and the project
start bounds only a task with no predecessors — and the pass now agrees on
384 of BOILER's 451, 247 of KILN's 417 and 1,645 of CALCINER's 1,763, with
what remains named per row and pinned in `tests/test_forward_pass_boiler.py`.

**Backward pass, float and criticality (S4).** `sto.core.engine.backward` is the
forward pass transposed — the four types read the opposite end of the opposite
activity, `latest_span` mirrors `earliest_span`, and lag is walked back — so
most of its suite states a relation between the two passes and checks it over
generated networks rather than checking a value in one direction. Two bugs came
out of exactly those: a milestone snapped backwards took the finish-side answer
when a milestone is a coordinate work *starts* at, and the pass refused a late
date before the project start when that is precisely what an over-committed
schedule has to be able to report. A late constraint now earns negative float,
as the forward pass promised it would; ALAP is carried through both passes
rather than guessed at.

Float and criticality are `sto.core.engine.criticality`, and their three open
questions were settled against the real files rather than argued (ADR-008).
Measured on Microsoft Project's own stored dates, so our forward pass's
disagreement could not contaminate the answer: a float is **working time on the
activity's calendar**, which reproduces the slack BOILER stores where the
elapsed reading does not; a total float is **the smaller of the start float and
the finish float**, which reproduces every activity of KILN and of CALCINER
where neither component alone does. Free float is measured against the
successors' early dates and reproduces the stored free slack on about
ninety-eight rows in a hundred of every real schedule here. Criticality is
`total float <= threshold` — and the threshold turned out to be measurable
after all, because CALCINER is the one file in the estate that declares a
`CriticalSlackLimit`, which reads as working days of the project's own day.
That closes the importer gap this slice was carrying.

Not claimed: our own late dates reproduce Project's on none of the file's
activities and our own total float on nineteen, both inherited from the forward
pass. Our *free* float agrees on three hundred and fifty-one, which is what a
local quantity does when a global one is misplaced — the first evidence that
what remains is placement rather than logic. Every count is pinned in
`tests/test_backward_pass_boiler.py`, so closing the forward-pass difference
fails those assertions rather than passing unnoticed.

**Status date and progress (S5).** `sto.core.engine.progress` reads three facts
off each activity — an actual start, an actual finish, a remaining duration —
and puts it in one of three states, from the dates alone (ADR-009). A complete
activity is its two actual dates in both directions and nothing recomputes them;
an in-progress one keeps its actual start while its *remaining* duration is
placed as a fresh span, and its successors read the forecast finish that span
ends at. Both passes place the remaining duration, so float is measured from the
remaining start rather than from an actual start that cannot move. The
out-of-sequence policies are the project's: retained logic keeps the
predecessor's forecast finish over the remaining work, progress override
replaces it with the status date, and `actual_dates` is refused rather than
answered, because the corpus declares no forecast for it.

With the corpus's status cases the engine now runs every case the corpus
declares an answer for and does not hold back for levelling. `P1-G1` asks for
that *and* for byte-identity across processes, so both halves are asserted: the
case ids the suite runs must be exactly the corpus's own executable subset, and
one digest over every case's three pass fingerprints must be identical in three
subprocesses under three hash seeds.

The criticality rule S4 left open is closed, and it needed two halves rather
than one. In the two files Microsoft Project itself recalculated after progress
was entered, every completed activity carries late dates equal to its actual
dates, a stored slack of zero, and `Critical` false — so the backward pass pins
completed work, and criticality excludes it. The threshold rule alone is wrong
on all four of those rows.

Not claimed, and asserted so it cannot be forgotten: the day-5 candidate is an
oracle for reported work and **not** for slack. Its completed rows carry early
dates equal to their actuals, which the pass reproduces exactly, and late dates
three weeks later, because it was written by tooling rather than recalculated by
Project. Every one of its completed rows is already non-critical on slack alone,
so it cannot distinguish the two rules and is never quoted for them.

## Now: the engine and a local planner trial

Phase 0 passed on 2026-09-03 with every criterion crossed on its inputs
present. Phase 1 is the engine, one visible planner loop over it, and real
authentication, in this order (ADR-011 — the sidecar moved to Phase 3, where
the writers that need it live):

1. ~~Calendars~~ — done.
2. ~~Forward pass~~ — done against the corpus. The BOILER file-oracle
   difference is diagnosed (ADR-010): four Microsoft Project rules measured
   on three real files take the pass from one activity agreeing with the
   stored dates to 384 of 451, and what remains is twenty first mismatches
   across three files, each in a named class, with the rows behind them
   counted as triage rather than claimed as explained.
3. ~~Backward pass, float and criticality~~ — done. The float and criticality
   *rules* are settled against the real files (ADR-008); the *dates* still
   carry the forward pass's difference, which is the status date's to close as
   much as this slice's.
4. ~~Status date and progress~~ — done. The policies are settled against the
   corpus and completion against the genuine Project-recalculation pair; the
   status date itself is proven by the corpus alone, because no file here
   carries one inside its own schedule.
5. ~~Source meaning preserved before calculation~~ (`C1`) — done. The five
   ways the import-to-plan boundary turned unsupported input into an ordinary
   calculation are each a coded disposition now (ADR-012): a calendar the file
   does not carry excludes its row instead of inheriting the project default;
   `DurationFormat` is read, so an elapsed span runs on the clock and is
   labelled; a duration the parser could not read excludes its row rather than
   becoming zero work; a manual leaf is excluded and a project scheduled from
   its finish is refused; and two rows sharing one GUID in one snapshot keep
   two identities, reported on the reconciliation. Tested from XML through to
   the passes, which is the road the corpus cannot reach, and nothing new
   refuses an import.
6. **The two passes agree on their supported contract** (`C2`). The same
   review reproduced a free float that overstates safe delay across
   calendars, a discarded progress edge that can still refuse a schedule, a
   started-task constraint the forward pass defers and the backward pass
   applies, and a negative working lag whose inverse overshoots at a calendar
   gap. Fixed with the counterexamples pinned and an independent feasibility
   check over the returned late dates.
7. ~~WBS rollup, the eligibility re-partition and an independent validator~~
   (`S6`) — done. A summary's span is its children's, measured against the
   summary dates all three real files store: exact wherever the pass beneath
   it is, and every disagreement has a disagreeing leaf under it. The
   validator reads a finished result and checks the relations it claims
   without calling the passes that produced them, which is the shape of check
   that would have caught the cross-pass defects `C2` fixed by reading code.
   The re-partition the frozen plan describes was written against the previous
   engine's reason codes; none of them exists here and the cascade it wanted
   removed reaches no row in the estate, so the disposition partition is
   enforced instead of rebuilt
   (`docs/history/2026-09-08-rollup-and-validator.md`).
8. ~~The per-activity result projection~~ (`PL3`) — done. ADR-006 deferred it
   until its columns had meanings and a result type to mirror; S3 to S6 gave
   them both. A result carries the document hash it was computed from, the
   horizon, the policy, the threshold and every stage's profile, and hashes
   them with the rows, so two results that agree say so before anyone compares
   dates. `V002` stores a calculation the way a version is stored: immutably,
   a recalculation being a new row rather than an edit.
9. ~~The calculated schedule, persisted and visible~~ (`PL13`) — done. Stored
   baseline → plan and passes → a result bound to its input hash, engine
   profiles and dispositions → an API route → a task table and simple Gantt
   showing imported dates beside calculated ones, reloaded identically after a
   restart. The page reads through the verified loader, so what a reader sees
   is what the stored fingerprint attests to. With it the guards that flow
   needs: a parse or validation failure becomes a coded failed import rather
   than a server error, uploads are bounded, and one malformed stored document
   quarantines its project rather than aborting the rebuild of every other
   (`docs/history/2026-09-08-the-calculation-made-visible.md`).
10. **One planner scenario** (`PL14`): pick a supported task, change its
    duration, see its successors move, reset to the baseline, export, restart.
    The first consolidated vertical slice; the legacy workspace retires after
    this loop is accepted, not before.
11. **Real authentication** (`PL2`). Password with TOTP, server sessions,
    device tokens for the field app. Every route rejects an unauthenticated
    request, and a project is readable only by an actor authorised on it.

The MPXJ sidecar — carried from the frozen repository, widened to the full
canonical document, cross-checked against the Python importer on every
fixture, and the first native `.mpp` import — is Phase 3's, arriving when a
trial file needs it (ADR-011).

## Next: the rest of the roadmap

Live execution loop (progress reaches the live schedule in under a second, the
approved forecast only through review); export with the proven Microsoft Project
transaction and a bound evidence register; CMMS work orders through a mapped-file
adapter and then named SAP PM, Maximo and Oracle EAM adapters; then **cut-over**,
then resource levelling and operational constraints.

Cut-over comes before the levelling work, not after it. What the parity
checklist asks for is problems, evidence and critical updates, not levelling, so putting
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
| `PR-conformance-suite` | S3 | live | `tests/test_conformance_corpus.py` |
| `PR-evidence-register` | I13 | pending | docs/evidence/register.json exists |
| `PR-approved-forecast` | PL6 | pending | sto.execution.review imports |
| `PR-migrations` | PL1 | live | `tests/test_migrations_are_immutable.py` |
| `PR-legacy-retirement` | I4 | pending | src/sto/interchange exists |

<!-- roadmap:end rules -->

## Standing constraints

The engine's claims are bounded by the conformance suite and the file oracle.
No writer claims `native-evidence-derived` without an entry in `docs/evidence/`
for that target system and application build. Real customer schedules stay
outside the repository. `Shutdown-Tracker-Claude` stays deployed and untouched
until the parity checklist passes.

## Known gaps recorded, not hidden

- **Free float can exceed total float across differing calendars.** ADR-008
  records the relation as a finish-to-start theorem; it is also a
  single-calendar one. A predecessor whose own calendar is working where its
  successor's is a gap slips its own working time without moving the
  successor, so it holds free float the project does not allow — three such
  rows in KILN, five in CALCINER, six in the day-5 candidate, with no negative
  float involved. Measured in S6. The validator no longer rests on the
  theorem: it measures the reported free float by applying it, so it asks the
  question of every network whatever governs it, this fact included.

- **Where an activity starts when its predecessors bound only its finish is
  assumed, not measured.** Such a row has no bound on its start; it falls back
  to the project start, which is where Microsoft Project puts an ASAP task
  nothing else places and what every root already uses, but no file here
  exercises it — every such row in the estate is placed by its own duration
  rather than by the floor, on every horizon tried, and the counts behind that
  are in ADR-010 (amended 2026-09-08) with the run that produced them. The
  forward pass names any row that does rest on it, on
  `ForwardPass.unbounded_starts`, and on every real schedule here that list is
  empty. Settling the rule needs a file with an FF or SF successor long enough
  for the floor to bind.

- **An elapsed span runs on the clock; where it starts is unmeasured.** The
  span rule is corroborated — on every elapsed row in the estate the span
  Project stored equals the elapsed duration exactly. The rule C1 recorded for
  the *start* was withdrawn in C2: the offset that suggested it is inherited
  from the predecessors, and those rows' effective calendar is twenty-four
  hours, so there was nothing to snap to (ADR-012 as amended). The rows stay
  labelled `ACTIVITY_DURATION_ELAPSED`.
- ~~**An elapsed span starts at a working moment and then runs on the clock,
  and only the second half is implemented.**~~ Placing an elapsed duration on the
  continuous calendar reproduces both of CALCINER's elapsed rows exactly and
  puts both of BOILER's six and a half hours early — its resource calendar's
  opening time — so Project starts the span on the task's calendar and then
  counts clock time (ADR-012). The hybrid placement needs an activity-level
  flag through both passes and both fingerprints, so it is `C2`'s; the rows are
  labelled `ACTIVITY_DURATION_ELAPSED` and pinned as disagreeing. *Withdrawn
  2026-09-08; see the entry above.*
- **CALCINER carries a duplicate assignment GUID** (UIDs 14103 and 14104). The
  second row no longer takes the first's canonical identity; the pair is
  counted as `guid_duplicated_in_snapshot`. No duplicate *task* GUID exists in
  any real file here.

- **GUID is not a durable key on this site's Microsoft Project export path.**
  Between the two BOILER snapshots every shared task UID kept its work-order and
  operation key and carried a regenerated GUID, so the GUID rekey fallback in
  `IdentityMap` cannot fire on that path and a rule treating a changed GUID as
  a different row matches nothing (ADR-002, second amendment). Other builds and
  export routes are unmeasured, so the fallback stays. Reconciliation now
  counts matched rows whose GUID moved, which is how the next path gets
  measured. The fallback that does hold here is the work-order and operation
  pair — see the business-key gap below.
- **Lag calendar for Microsoft files — measured, and the assumption was
  wrong.** `ProjectSettings` still records `lag_calendar_policy = successor`,
  but the plan now resolves it to the successor's own *task* calendar or the
  project's, never a resource's: every one of the fifty-seven working-time lags
  in KILN and CALCINER that any calendar explains is explained by that, and the
  successor's effective calendar explained a third of KILN's (ADR-010). Both
  project calendars in the estate are twenty-four hours, so a lag on the
  project calendar and an elapsed lag cannot be told apart here; the plan uses
  the project calendar and labels each such edge
  (`RELATIONSHIP_LAG_ON_PROJECT_CALENDAR` on `Plan.assumed`: 14 in KILN, 41 in
  CALCINER, none in BOILER), so the choice is carried as an assumption rather
  than presented as measured.
- **Tasks whose resources are on several calendars are scheduled on the union
  of those calendars, as an assumption** (`ACTIVITY_RESOURCE_CALENDARS_UNITED`
  on `Plan.assumed`). Project's stored span for such a task is the envelope of
  its stored per-assignment spans on every such row in BOILER and KILN and all
  but three of CALCINER's; scheduling assignments is not built, and these rows
  are most of what the pass still gets wrong on CALCINER.
- **The successor of an inactive task follows no rule the files agree on.**
  Some sit where the inactive task's own predecessors would put them, some
  where their other predecessors do, some where nothing measured does. The edge
  is dropped and the row labelled `ACTIVITY_SUCCESSOR_OF_INACTIVE` once,
  however many inactive predecessors it has; on the progressed BOILER files,
  which carry twenty-one inactive rows, this is the largest remaining class.
- **Two CALCINER rows with `IgnoreResourceCalendar` set and a task calendar of
  their own, and one KILN row Project placed continuously on a resource
  calendar that compiles here as a day shift, are unexplained.** Named in
  `docs/history/2026-09-05-forward-pass-residue-diagnosed.md`.
- **KILN's late dates agree with Project on none of its rows** because its
  project finish is set by a tail that is still inherited-wrong; it closes with
  the first mismatches above, not separately.
- **No Primavera file exists anywhere in the estate.** Until one arrives the XER
  and P6 XML paths have no oracle and every P6 writer stays `diagnostic`.
- **`MsSummaryProjection` is populated but nothing writes it back yet**; it
  becomes load-bearing when the MSPDI writer lands.
- **No file in this estate can test the status date.** Every BOILER variant
  declares `StatusDate` 2025-05-09 and starts on 2026-09-13 — sixteen months
  later, from the same 2024-25 template the calendars came from. The status date
  therefore falls outside the compiled window on all of them, `build_plan`
  reports that on `status_time_outside_window` and carries no status time rather
  than scheduling unfinished work from a date sixteen months in the past, and
  the rule that remaining work starts at the status date is proven by the
  conformance corpus alone. `tests/test_progress_boiler.py` asserts this, so a
  file that one day carries a usable status date fails and asks for the claim to
  be widened.
- **The late dates of an in-progress activity are not measured.** No file here
  carries a Project-recalculated late date for an activity that had started and
  not finished, so the backward pass places its remaining duration as the mirror
  of the forward pass and that is not claimed to be what Project does.
- **Remaining work is floored at the actual start, not at the end of the work
  already done.** The one in-progress row in the estate settles that started
  work is placed from its actual start rather than the project start — its
  forecast finish now reproduces Project's exactly — but it reports no actual
  duration and no resume date, so the two floors coincide on it. A row that has
  consumed part of its duration, or carries a Project `Stop`/`Resume` pair,
  would need the remaining span to begin after the completed portion, and that
  is unmeasured. `tests/test_progress_boiler.py` pins the row's zero actual
  duration so the first file that differs asks the question.
- **A constraint on an activity that has started is reported, not applied.**
  What a finish-side constraint should do to the remaining span of work already
  under way has no corpus case and no real file to measure on, so the forward
  pass carries it on `deferred_constraints` rather than scheduling the row as
  if it were unconstrained or guessing what Project would do.
- **Field reports will arrive as percentages, and the engine reads dates and
  remaining durations.** That is ADR-009's decision and it holds; what it
  implies is that the execution layer (S7) owes a conversion at the API edge —
  a reported percentage into a remaining duration, with the rule written down —
  and the engine is not the place for it.
- **Whether Primavera's data date is an implicit floor under unstarted work is
  open.** Microsoft Project does not floor it — rescheduling uncompleted work is
  a command a planner runs — and the corpus declares no floor either, so none is
  applied. Settling it needs `DEP-P6-FILE`.
- **Criticality on a progressed schedule is not the threshold rule.** On the
  un-progressed BOILER snapshot `total float <= threshold` reproduces the flag
  Microsoft Project stored for every activity in the file; on both progressed
  snapshots it does not, because a complete activity is not critical whatever
  its slack. Measured, not guessed, and owed to S5 with the status date.
- **Two BOILER rows have a stored total slack larger than either of their own
  date differences**, so the rule that explains the other 449 does not explain
  them. Counted in `tests/test_backward_pass_boiler.py` rather than absorbed.

### Carried from the PR #31 and #32 reviews

Neither review was answered on its pull request: #31's six findings were merged
past, and #32 merged before its review ran. Both were answered on 2026-09-05 in
one change (`docs/history/2026-09-05-post-s5-review.md`). Fixed: remaining
work floored at the actual start, with the project start no longer a bound on
started work; the progress policy reaching the backward pass and the free
float; work that has started with no remaining duration refused; constraints on
started work reported rather than dropped; the progress state and the two
component floats hashed into the fingerprints; a project late finish past the
horizon refused; the two passes bound to the network by fingerprint; the float's
refusals coded; and the false aggregate in the S4 history entry. Rejected with a
measurement: the negative-lag inversion, which holds from every coordinate a
placed date can occupy and departs only inside a gap by zero working time,
pinned in `tests/test_backward_pass.py`.

### Carried from the PR #33 and #34 reviews

PR #33 merged five minutes before its review landed, so its three findings
joined PR #34's five and all eight were answered on the residue branch
(`docs/history/2026-09-07-post-residue-review.md`), each pinned in
`tests/test_post_residue_review.py`. Fixed: the progress policy travels on the
forward pass and the backward pass reads it there, refusing a different one
by name (`SCHEDULE_POLICY_MISMATCH`) — the corpus digest had been attesting
SEM-STA-044 with its two passes under different policies; the released edges
are hashed into the backward fingerprint (`sto-backward-pass-v3`); an SS or SF
edge out of started work is anchored on the actual start in the free float, as
the forward pass anchored it; a lag with no calendar of its own falls back to
the successor's scheduling calendar in the float, not its measuring calendar;
the driver replay floors where the bounds did, so a lead-placed task before
the project start reports the edge that moved it; the project-calendar lag
choice is labelled; a successor of several inactive tasks is labelled once;
and `IgnoreResourceCalendar` is recognised in both spellings `xsd:boolean`
allows. No agreement count moved.

The reviewer's second pass on that commit raised five more, and the
comprehensive review of 2026-09-07 reproduced every one; all five are fixed
on the same branch (`docs/history/2026-09-07-post-residue-review.md`, second
section), pinned in the same file. Fixed: an explicit canonical `LagCalendar.SUCCESSOR`
now means the successor's scheduling calendar, and the Microsoft task-or-project
rule applies only to relationships that inherit the project's policy; a row
whose measuring calendar has no working time is excluded
(`ACTIVITY_MEASURE_CALENDAR_EMPTY`) rather than reported as zero float and
critical, and a directly built network refuses it; the backward pass carries
its progress policy and hashes it (introduced in `sto-backward-pass-v4`), and the float
refuses a backward pass under one policy beside a forward pass under another
(`SCHEDULE_POLICY_MISMATCH`); the multi-resource assumption is recorded only
once the row is scheduled, and the plan refuses to carry an assumption about
a row it excluded; and a relationship bound below the successor calendar's
floor no longer counts as the driver of a task it did not move. No agreement
count moved. The same change corrected ADR-010's "before" figures for KILN
and CALCINER to what `main` actually produces under the test horizon (29 and
130, not 36 and 260), pinned the late-date and float counts for all three
files, and reworded "inherited" as what it is — a row with a mismatching
predecessor, triage rather than a causal claim.

### Carried from the PR #22 review, against the slice that owns each

Automated review raised 27 findings. The correctness defects are fixed and have
regression tests. These are real but belong to a later slice, and are recorded
here so they are not rediscovered as surprises:

| Gap | Owed to |
|---|---|
| `Assignment.timephased_ref` is never populated, so resource curves and exports cannot find the retained source payload. | S8 |
| `MsSummaryProjection` carries only part of a summary task's constraints, calendars, priority and custom fields, and nothing writes it back. | S8, writeback |
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

The file-oracle cases skip unless the real schedules are present; point
`STO_BOILER_BEFORE`, `STO_BOILER_DAY5`, `STO_KILN` and `STO_CALCINER` at them to
run them. `P1-G2` and `P1-G3` rest on those cases, so cross a gate with
`STO_REQUIRE_BOILER=1` set — their absence then fails instead of skipping
quietly. The float and criticality rules are evidence from KILN and CALCINER as
much as from BOILER, which is why those two now have variables of their own.
`fixtures/README.md` records every file's hash, what it proves and how to
recover it — including two that cannot be recovered and need backing up.
