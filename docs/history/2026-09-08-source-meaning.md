# 2026-09-08 — Source meaning preserved before calculation (C1)

The first slice of the resequenced Phase 1 (ADR-011), answering findings F01
to F05 of the 2026-09-07 comprehensive repository review. ADR-012 holds the
decisions; this is what was measured on the way to them.

## The five defects, as they behaved before

Each was reproduced through the real importer, the real migration and the real
plan before anything was changed:

| What the file said | What the engine did |
|---|---|
| `CalendarUID 999`, which the file does not carry | importer warned, canonical `calendar_uid` `None`, row scheduled on the project default, no exclusion |
| eight hours with `DurationFormat 6` (elapsed hours) | `unit None`, `elapsed False`, placed 08:00–17:00 across lunch as working time |
| `Duration P1M`, which the parser rejects | canonical duration `None`, scheduled as 08:00–08:00, successors advanced |
| `Duration PT0.5S` | truncated to zero seconds |
| `<Manual>1</Manual>` | scheduled as automatic; no exclusion |
| `<ScheduleFromStart>0</ScheduleFromStart>` | identical network fingerprint to from-start |
| two tasks, one GUID | two rows, **one** canonical identity |

The importer's warnings were also dropped at the API boundary: an accepted
import recorded `warning_count` zero however many the parse produced.

## Elapsed time: what Project actually does

The interesting measurement. With `DurationFormat` read and the span placed on
the continuous calendar:

| File | Rows | Ours | Project stored |
|---|---|---|---|
| CALCINER | 2 × `eh` 240h | exact on both | — |
| BOILER | 2 × `ed` 96h | 6h30 early on both | 06:30 start |

CALCINER's project calendar runs twenty-four hours, so continuous placement
and its own calendar agree. BOILER's does not, and the constant six-and-a-half
hour offset is exactly its resource calendar's opening time: Project put the
*start* at the next working moment on the task's calendar and then ran the
span on the clock. That is a rule, and it reproduces both rows. It is not
implemented here because it needs a per-activity elapsed flag carried through
both passes and both fingerprints, which is pass-level work and belongs to C2;
the rows are labelled `ACTIVITY_DURATION_ELAPSED` and pinned as still
disagreeing, so the implementation has an oracle waiting for it.

## A duplicate GUID that is really there

CALCINER's assignments 14103 and 14104 both carry
`7C243A9C-6913-F111-96ED-28952922E2E5`. The review looked for duplicate *task*
GUIDs in the three real files and correctly found none; this is an assignment,
and before this slice the second row took the first's canonical identity
without a word. It is now reported as `guid_duplicated_in_snapshot` and each
row keeps its own identity. The cross-snapshot GUID fallback that a re-import
depends on is unchanged, and a test holds it: a row whose source UID changes
between snapshots still rekeys onto its GUID.

## What moved, and what did not

`sto reconcile` on the BOILER pair is unchanged — 447 matched, 18 new, 13
departed activities, 341/136/131 assignments — which is the estate's rule for
any identity change. BOILER's stored-date agreement is unchanged at 384 of
451: its two elapsed rows disagreed before and disagree still, for the reason
above. KILN's compared cohort falls from 417 to 416, because its one manually
scheduled leaf is now excluded rather than scheduled as if it were automatic;
its exact count is unchanged at 247, and ADR-008's float rule still explains
every row it is asked about, 416 of 416. CALCINER is unchanged at 1,645 of
1,763.

## Rejected

Refusing an import that carries any of these states: every real file in the
estate must keep importing, and the plan can report what it cannot schedule.
Implementing the hybrid elapsed placement in this slice. Rejecting a document
for duplicate GUIDs, which the PR #22 review already considered and declined
for the same reason — it buys an unobserved case at the cost of a new way for
a real file to stop importing.

## The slice's own review, answered the same day

Four findings, all real, all in the class this slice exists to close.

**The GUID quarantine was half a fix.** Clearing the GUID on the second row
left the first row's mapping in `IdentityMap.by_guid`, so a later import that
renumbered *either* row would have been rekeyed onto whichever appeared first
— durable identity corruption arriving one import after the defect that caused
it. Duplicates are now found in a pass over the document before any row is
resolved, and the GUID is quarantined on the identity map itself: dropped from
`by_guid`, never learned, never matched on, and carried through `to_dict`. On
CALCINER the quarantine holds and all 3,114 assignments keep distinct
identities.

**The unresolved reference was not actually preserved.** The ADR said the
reference survives; the row carried only the one-way minted id. It now carries
`calendar_ref_unresolved` with the text the file gave.

**Unsupported durations still vanished everywhere else.** Only the planned and
remaining durations kept a marker; work, actual duration and the assignment
work triple silently became absent or, through `WorkTriple`, a measured zero.
Each now records what could not be read on its own row.

**A null `DurationFormat` was recorded and never read.** Codes 21 and 53 name
no unit, and the reviewer was right that a field nothing reads is either a
disposition or dead weight. Measured before choosing: KILN's forty-five such
rows carry ordinary ISO durations from zero to four hours and schedule like
any other row, so they are ordinary work, the code stays on
`Duration.source_format_code`, and the redundant marker is gone. Excluding
forty-three schedulable KILN rows for an unset display unit would have been
the trade this repository refuses.

## A second pass, and the finding that mattered most

Three more, all real, all P1.

**Excluding a row let its successor advance — the exact harm the exclusion
exists to prevent.** With the predecessor gone the edge is dropped, and a
successor with no predecessor at all is a root: the forward pass floors it at
the project start, *earlier* than the file puts it. The first version of
`test_unknown_work_does_not_let_its_successor_advance` asserted the exclusion
codes and never looked at where the successor landed, so it passed while
claiming something false. The cut now follows the chain to a fixed point and
reports every row as `ACTIVITY_PREDECESSOR_NOT_SCHEDULED`. It deliberately
does not follow an inactive predecessor, which has a measured rule, or a
summary, whose span is S6's rollup. On KILN the one manually scheduled row has
no successors at all, so no real file loses a row to this.

**An unknown `DurationFormat` was still working time.** `999`, or anything
non-numeric, produced `unit None, elapsed False` and scheduled ordinarily —
the same defect as reading no format at all, one level up. Such a row is now
excluded with the text the file gave. All three real files use known codes.

**Baseline values had nowhere to record what could not be read.** The previous
commit discarded them with a comment claiming the activity's own marker
covered it, which is false: a live duration can parse while its baseline does
not, and a baseline can belong to a WBS node. `BaselineActivityState` now has
`source_fields`; the codec omits a defaulted field, so no stored document's
hash moves.

The suite runs clean with no skips under the command in
`docs/goals/ACTIVE.md`, and no agreement count moved.

## A third pass, and what it caught in the second pass's fixes

Four more, all real, three of them defects in the cut that had just been added.

**The cut took completed work with it.** A complete activity is pinned to its
actual dates by both passes and reads no predecessor, so removing one because
something upstream is unreadable discards progress the file records — and then
cascades that loss to its own successors, which had a known date to read. The
cut now skips completed rows and stops at them.

**An omitted `<ScheduleFromStart>` read as backward scheduling.** The importer
reports an absent element as `None`, and the migration's truthiness test made
that `FROM_FINISH`; with the new refusal in front of it, the whole plan would
have been refused for a file that never asked for backward scheduling. Only an
explicit `0` is backward now.

**A resource's broken calendar reference was not preserved**, only an
activity's — and a resource's broken calendar is what excludes the activity
assigned to it, so that exclusion named nothing but a synthetic UUID.

**A test count in this entry.** `AGENTS.md` names tests beside files and cases
as counts that must not appear in prose, and it had one. Unlike a slice count
in a dated record, a test count never ages into a true historical statement —
it ages into a wrong one that a reader can disprove with one command — so the
guard added with the resequencing now covers every document for that pattern,
`docs/adr/` and `docs/history/` included. It caught one more from 2026-09-03.
