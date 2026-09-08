# ADR-012: Source meaning is preserved or dispositioned, never defaulted

Status: accepted, 2026-09-08

## Context

The comprehensive repository review of 2026-09-07 found the engine's most
consequential defects not in the passes but on the road to them. Five source
states arrived at `build_plan` already flattened into ordinary, supported
values, and the calculation that followed looked exactly like a calculation
over a file the engine understood:

- an activity naming a calendar the file does not carry became an activity
  naming none, which inherits the project's default;
- an elapsed duration became working time, because the migration set
  `elapsed=False` on every duration and never read `DurationFormat` — the
  untouched BOILER and CALCINER each carry two active elapsed tasks, so the
  code comment saying no real file has one was false;
- a duration the importer could not parse became `None` and then zero, so
  uninterpreted work disappeared and its successors advanced;
- `manual` and `schedule_direction` were retained on the canonical model and
  read by nothing, so a manually placed row and a project scheduled from its
  finish produced the same network fingerprint as automatic and from-start;
- two rows of one snapshot sharing a GUID collapsed onto one canonical
  identity, and the persistence layer stores a document without ever building
  the network that would have rejected it.

Each was reproduced here before it was fixed, and the measurements are in
`docs/history/2026-09-08-source-meaning.md`.

The conformance corpus cannot catch any of this: it constructs a `Network`
directly, so it proves the passes behave over a network that was built
correctly. That is why a large, genuinely passing suite sat above all five.

## Decision

**A source state the engine does not support becomes a coded disposition, a
labelled assumption, or a refusal — never a default.** Concretely:

**Unresolved references keep their reference.** A calendar id the file names
and does not carry is minted as a canonical id the calendar table has no row
for, so the plan looks it up, fails, and excludes the row as
`ACTIVITY_CALENDAR_UNRESOLVED`. The minting is one-way, so the reference the
file actually carried travels beside it on the row's `source_fields` as
`calendar_ref_unresolved` — on a resource as much as on an activity, since a
resource's broken calendar is what excludes the activity assigned to it: an
exclusion that names only a synthetic UUID cannot be acted on without
reopening the source. An activity naming *no* calendar still
inherits the project's. The importer's warnings travel with the import: the
batch records the count and the API returns them, so an accepted import with
warnings is no longer indistinguishable from a clean one.

**`DurationFormat` is meaning, not display.** The migration reads it, fills
`Duration.unit` and `source_format_code`, and sets `elapsed` from the even
codes of Microsoft's own table. An elapsed span is placed on the continuous
calendar, because elapsed time counts every hour on the clock, and the row is
labelled `ACTIVITY_DURATION_ELAPSED` rather than claimed: see the measurement
below, which the rule reproduces on CALCINER and does not yet on BOILER.

**A row whose dates are unknown takes its successors with it.** Excluding the
row alone drops the edge, which leaves the successor with no predecessor and
lets the forward pass floor it at the *project start* — earlier than the file
puts it, and the same false advancement the exclusion was meant to prevent.
The cut is walked to a fixed point and each row is reported as
`ACTIVITY_PREDECESSOR_NOT_SCHEDULED` naming the row it came from.
`UNKNOWN_DATE_EXCLUSIONS` in `sto.core.engine.plan` is the set it follows, and
two exclusions are deliberately outside it: an inactive predecessor has a
measured rule of its own (ADR-010: drop the edge, schedule the successor,
label it), and a summary or level-of-effort row takes its span from its
children, which is S6's rollup rather than an unknown. **Completed work is
outside it too, in both directions**: a complete activity is pinned to its
actual dates by both passes and reads no predecessor (ADR-009), so cutting one
would discard recorded progress, and the cut does not travel through it either
— everything after it reads its actual finish, which is known.

**An unknown `DurationFormat` is not working time.** A code outside
Microsoft's table names semantics this code does not have — above all, whether
the span is elapsed — so the row is excluded as
`ACTIVITY_DURATION_FORMAT_UNSUPPORTED` with the text the file carried, rather
than defaulted to the calendar. Non-numeric text is the same case. Every code
in the three real files is a known one, so nothing moves.

**Unknown work is not zero work, on any field.** The migration distinguishes
three states — a duration, nothing, and something it could not read — and
carries the third with the text it could not read. A planned or remaining
duration the importer marked unsupported, or one that is not a whole number of
seconds, excludes the row (`ACTIVITY_DURATION_UNSUPPORTED`,
`ACTIVITY_DURATION_NON_INTEGRAL`) instead of scheduling zero. The fields the
engine does not schedule on carry the same fact rather than losing it: work,
actual duration and the assignment work triple record what could not be read
on their own `source_fields`, because `WorkTriple` counts seconds and would
otherwise store an unreadable value as a measured zero. `BaselineActivityState`
gains a `source_fields` of its own for the same reason and cannot borrow the
activity's: a live duration parses while its baseline does not. The codec omits
a field at its default, so adding it leaves every existing document's hash
where it was. A null placeholder row
is `ACTIVITY_NULL_PLACEHOLDER`.

**A null `DurationFormat` is display, and is scheduled.** Microsoft's codes 21
and 53 name no unit, but `<Duration>` is an ISO span either way. KILN carries
forty-five such rows — milestones and tasks, durations from zero to four hours
— and they are ordinary work. The code is preserved on
`Duration.source_format_code`; nothing is dispositioned, because excluding
real work for an unset display unit is exactly the trade this ADR refuses.

**Unsupported scheduling policy is reported at the level it applies to.** A
manually scheduled leaf is excluded (`ACTIVITY_MANUALLY_SCHEDULED`) — KILN has
one. A project scheduled from its finish reverses which pass is authoritative
for every row, so it is not a per-row disposition: `build_plan` refuses with
`PROJECT_SCHEDULED_FROM_FINISH`. Only an explicit
`<ScheduleFromStart>0</ScheduleFromStart>` is that: an absent element is not a
choice, Microsoft Project's own default is forward, and reading absence as
backward would refuse a file that never asked for it.

**A GUID identifies one row of one document, and once two rows have claimed it
it identifies neither.** Duplicates are found before any row is resolved, and
the GUID is **quarantined on the identity map**, which persists: it is dropped
from `by_guid`, never learned again, and never matched on. Clearing it on the
second row alone would not have been enough — the first row would already have
taught the map that GUID, so a later import renumbering either row would be
rekeyed onto whichever appeared first, which is durable identity corruption
arriving one import after the defect. Both rows resolve on their own source
UIDs and the pair is reported as `guid_duplicated_in_snapshot`. The
cross-*snapshot* GUID fallback, which is what an ordinary re-import needs, is
untouched.

**Nothing here refuses an import.** Every rule above produces a disposition on
the plan, not an error from the importer or the migration. A real file that
imports today still imports.

## Measured

**Microsoft Project starts an elapsed span at a working moment and then counts
clock time.** CALCINER's two active elapsed rows (`eh`, 240 hours) are
reproduced *exactly* by placing the span on the continuous calendar, because
its project calendar runs twenty-four hours. BOILER's two (`ed`, 96 hours) are
reproduced six and a half hours early — exactly the start of its resource
calendar's working day — so Project placed the start on the task's calendar
and then ran the span on the clock. That hybrid placement is not implemented:
it needs a per-activity flag through both passes and both fingerprints, which
is C2's work. Until then the rows are labelled, and
`tests/test_forward_pass_boiler.py` pins BOILER's two as still disagreeing so
that implementing the rule has an oracle.

**CALCINER carries a duplicate assignment GUID.** Assignment UIDs 14103 and
14104 share `7C243A9C-6913-F111-96ED-28952922E2E5`. Before this change the
second silently took the first's canonical identity. No duplicate *task* GUID
exists in any of the three real files, which is why the earlier review looked
and found none.

**Nothing else moved.** The BOILER pair reconciles exactly as recorded —
447 matched, 18 new, 13 departed activities; 341, 136, 131 assignments — and
BOILER's agreement with Project's stored dates is unchanged at 384 of 451,
because its elapsed rows disagreed before and disagree still. KILN's compared
cohort drops by one, from 417 to 416, because its manual leaf is no longer
scheduled as if it were automatic; the float rule still explains every row it
is asked about.

## Consequences

`Plan.excluded` gains five codes and `Plan.assumed` one; `PlanError` is the
plan's first project-level refusal. Every real-file pin that names a cohort
size is updated with the reason. The API's import response carries the
importer's warnings and the new identity counter. `MsSummaryProjection`,
assignment `timephased_ref` and typed UDF values remain unfilled — they are
writeback concerns and stay with S8.

Rejected: refusing an import that carries any of these states (it would stop
real files importing for cases the plan can report instead); implementing the
hybrid elapsed placement here (it is pass-level work and belongs to C2); and
treating a duplicate GUID as grounds to reject the document, which the PR-22
review had already considered and declined.
