# 2026-09-08 — The comprehensive review answered, and Phase 1 resequenced

## What was reviewed

A read-only comprehensive review of this repository, dated 2026-09-07, over
`main` at `0ad4bd7` and PR #34 at `4271abd`: architecture, engine, Microsoft
Project compatibility, persistence and API, twenty-one ranked findings, a
readiness matrix, a recommended sequence and a stop-doing list. It ran the
suites on both revisions, recomputed every agreement count independently, and
reproduced every defect it reports with a counterexample through the actual
importer, migration, plan and passes. Its report is kept outside the
repository with the transcripts; this entry records what it found, what was
checked here, and what changed because of it.

## Its verdict, and what held on inspection

Continue here; no restart. The canonical model, the version envelope, the CPM
core and the pinned corpus are real improvements; the consolidation is
incomplete at the product boundary, where the new API imports and stores a
schedule and never calls the new scheduler; the engine is a credible bounded
backend and not an unrestricted forecast authority, because the
source-to-model boundary defaults unsupported input rather than refusing it.
PR #34: correct its five current-head findings, then merge.

Checked here on 2026-09-08 before anything was changed:

- The reviewer's second pass on `4271abd` had landed seventeen minutes after
  that commit and its five threads were unanswered; they are the review's
  F07–F11 and every one reproduced.
- The branch ran 502 tests with no skips against the real schedules and the
  upstream corpus.
- The day-5 candidate, which the review could not obtain and therefore marked
  every claim resting on it "not re-verified", is present on this machine. Its
  off-machine copy is still owed (`DEP-DAY5-BACKUP`).
- `main` under the horizon the tests use agrees with Project's stored dates on
  BOILER 1, KILN 29, CALCINER 130 — the review's figures, not the 36 and 260
  ADR-010 had recorded as "before".
- BOILER carries six non-zero lags, all elapsed leads; the post-residue entry
  had said all its lags were zero.
- Everything the review's F01–F05 describe is in the code as described: the
  migration sets `elapsed=False` on every duration and never reads
  `DurationFormat`; the plan reads neither `Activity.manual` nor
  `ProjectSettings.schedule_direction`; an unresolved `CalendarUID` becomes
  `None`; a duration the importer could not parse becomes zero; a GUID seen
  earlier in the same snapshot rekeys the next row that carries it.

The five PR findings and the evidence wording were answered on the branch the
same day (`2026-09-07-post-residue-review.md`, second section).

## Decisions

**Adopt the review's resequencing.** ADR-011: Phase 1 becomes "Engine and
local planner trial". Two correction slices, `C1` (source meaning) and `C2`
(cross-pass contract), precede S6; the result projection is followed by
`PL13`, the calculated schedule persisted and visible, and `PL14`, one
planner scenario; the sidecar slices and their two gate criteria move to
Phase 3; the authentication criterion now asks for actual rejection of an
unauthenticated request rather than the absence of one header. Phase 1's
remaining effort is twenty slice-days, Phase 3 gains thirteen.

**The resequencing's own review, answered the same day.** Four findings, all
real. The trial gate asked for calculation, editing, reset and restart but not
for the export `PL14` defines, so it could have been marked met without one;
`P1-G4` now asks for the export too. ADR-011's consequences hard-coded the
roadmap's own bookkeeping — and said "eleven slices instead of eleven", which
means nothing — so it names the slices that moved instead, and
`tests/test_governance_references.py` now fails on a prose count of slices,
slice-days or gate criteria in the documents that describe the repository now.
It caught one more the moment it was written, in `docs/goals/ACTIVE.md`'s
validation section. The README's replacement sentence still implied one
connected workflow, which is the overstatement this change exists to correct,
so it now says the import-and-store path and the engine are two things `PL13`
will join. And the "Now" heading still said "engine and interchange spine".

**Scope of the next pass.** PR #34 corrections, then `C1` as one PR. `C2`,
S6 and the rest follow in the roadmap's order.

**Not taken from the review**, recorded so it is not re-argued: a general
property-testing or hardening programme (the review itself warns against it);
retiring the legacy workspace or importer before the replacement loop is
accepted; any P6, CMMS or levelling work ahead of the trial; and Office.js as a
substitute for the proven completion transaction.

## Corrections

ADR-010's evidence table now names the revision and horizon "before" means,
carries the corrected KILN and CALCINER figures, pins the late-date and float
counts for all three files, and calls a row with a mismatching predecessor
exactly that — triage, not an explanation. The fixture README's day-5 row says
what the file is an oracle for and what it is not. README and AGENTS no longer
describe CMMS and P6 import, real-time tracking and export in the present
tense.
