# P1 evidence closure and P2 entry decision — 2026-09-20

This record answers only whether the present evidence satisfies P1-G2 and
P1-G3, and whether the first bounded live-progress slice can be proposed while
those interoperability claims remain open. The aggregate measurements are
machine-readable in `docs/evidence/p1-gate-entry-decision-2026-09-20.json`.
No customer task names or schedule contents are recorded here.

## Verified inputs

The supplied consolidation archive is the already-recorded object with SHA-256
`67f4766158c7b76284d8f997cd0345391bb270d4b762510bef59fe4a5ef4c730`.
It supplied the untouched BOILER identity control. The before, after-native,
task-43 candidate and task-43 Project-saved files were read from frozen
`dezrobbo1/Shutdown-Tracker-Claude` revision
`135218f6f3a6f6fe91ce193d0ee3776ebf0eedbe`; their byte sizes, full hashes and
stored builds match `fixtures/README.md`.

The exact day-five candidate is **NOT AVAILABLE**. Its surviving record is
3,747,935 bytes and a SHA-256 prefix `a8d44aa23e20c510`; no historical full
digest is known. It was absent from the unchanged, hash-identical consolidation
archive and from the documented frozen fixture repository. It was not
reconstructed or replaced.

## P1-G3: bounded native-transition classification

The before/after-native files are genuine Project-saved evidence from build
`16.0.20228.20188`, but they are not a controlled three-edit pair. The fresh
source-UID inventory is:

| Cohort | Rows | Disposition |
|---|---:|---|
| Common | 447 | 27 unchanged; 3 exact documented completion transitions; 417 `UNEXPLAINED` |
| Before only | 13 | unresolved identity/input change |
| After only | 19 | unresolved identity/input change |

The 420 changed common rows reproduce the historical inventory. The new bounded
classifier recognizes only the three rows whose changed field set exactly
matches the documented native completion contract: actual start and finish,
remaining duration and percent complete, plus Project's measured late-date and
total-float consequence. An extra changed field on even one of those rows makes
that row `UNEXPLAINED`. Start/Finish and EarlyStart/EarlyFinish are compared as
four distinct fields.

The other 417 changed common rows remain `UNEXPLAINED`; the 32 rows found on
only one side remain unresolved rather than being treated as intentional
additions or removals. This is not a finding that 449 rows are wrong. It is a
finding that this pair cannot causally establish that those differences are
expected. The files also differ in imported source/progress fields that
confound interpretation: among common activities there are changes to planned
duration, active state, planned work, calendar reference and remaining
duration, and the relationship signature inventory is 600 before versus 637
after. Those facts prevent a truthful
"progress edits caused every downstream change" conclusion.

The task-43 native round trip remains valid for its separate, narrow claim: one
supported completion transaction survived Project open/recalculate/save. It is
not evidence that explains this broader transition.

## P1-G2: day-five criterion

The baseline stored-field packet still proves coded dispositions and records
the current BOILER/KILN/CALCINER agreement measurements. It does not substitute
for the second BOILER snapshot required by G2. Because the exact day-five file
is absent, required-fixture mode fails and G2 remains unmet. Even if recovered,
that tooling-written file can measure reported early work but cannot serve as a
native oracle for late dates, float or criticality.

## Decision

### A. Engine and product implementation

The 47-case deterministic semantic corpus, persisted planner scenario and real
authenticated project boundary are implemented and executable. The current
engine has an explicit supported/assumed/excluded result model. This assessment
found no supported-input correctness witness and changes no scheduling code.

### B. Interoperability evidence

P1-G2 and P1-G3 remain open. G2 is blocked by an unavailable exact fixture.
G3 is blocked by insufficient causal evidence in a confounded native pair, not
by missing classification tooling: the bounded classifier now reports the
uncertainty explicitly. No fresh Microsoft Project execution occurred in this
run.

### C. Development entry

**P1 EVIDENCE REMAINS OPEN — LIMITED DEVELOPMENT EXCEPTION PROPOSED.** This is
not an enacted waiver and does not mark P1 passed. If the owner explicitly
approves it, the first S7/PL4 slice may use controlled synthetic/canonical input
inside the engine's labelled supported envelope, while making no Microsoft
Project interoperability claim and leaving both gate flags false.

The bounded slice is:

1. an authorised actor reports actual start plus explicit remaining duration
   for one eligible leaf activity;
2. an append-only update records actor, project, baseline/live version,
   activity, values and timestamp;
3. the existing production scheduler performs a full deterministic
   recalculation and persists a visibly **live/unreviewed** result;
4. restart and replay from the immutable baseline plus update log reproduce the
   same head hash.

Acceptance excludes partial-progress MSPDI writing, incremental rescheduling,
latency claims, approvals, approved forecast, offline operation, event streams,
multi-edit scenarios and Phase-3 returned-file classification.

To close the existing evidence gate without changing its meaning, recover the
exact day-five object and obtain a controlled native before/after transition
whose only intentional source change is recorded. If the historical inputs
cannot be recovered or controlled, any replacement criterion requires an
explicit roadmap decision; this record does not enact one.
