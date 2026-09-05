# ADR-010: Project schedules on the resource calendar, measures on the task calendar, and floors only roots at the project start

Status: accepted, 2026-09-05

## Context

The forward pass agreed with the dates Microsoft Project stored for the
un-progressed BOILER snapshot on one activity of four hundred and fifty-one,
recorded undiagnosed on 2026-09-03 with what had been ruled out: no
constraints, no manual rows, no levelling delay, all links finish-to-start.
Two clusters were named and unexplained — thirty-eight rows exactly
twenty-eight days out, forty-nine exactly half an hour — and a local quantity,
free float, agreed far better than a global one, which suggested the logic was
right and the placement was not. Gate criteria P1-G2 and P1-G3 rest on closing
this, and the roadmap had no time in which to do it.

Four questions turned out to be open, and every one was asked of the real files
rather than of documentation: which calendar a task is scheduled on, which
calendar a lag is consumed on, which calendar slack is measured in, and whether
the project start bounds a task that has predecessors.

## Decision

**A task is scheduled on its resources' calendar.** A task with no calendar of
its own and one assigned resource is placed on the resource's calendar, not the
project's. A task with its own calendar and a resource is placed on the
intersection of the two. The task's `IgnoreResourceCalendar` flag restores its
own calendar; the migration carries the flag as the source field
`ignore_resource_calendar_source`. A task with no resource calendar is placed on
its own or the project's. A task whose resources are on **several** calendars
is placed on their union and reported on `Plan.assumed` as
`ACTIVITY_RESOURCE_CALENDARS_UNITED`: Project's answer for those rows is the
envelope of its per-assignment spans, which this engine does not compute.

**A lag is consumed on the successor's own task calendar, or the project's when
it has none** — never on a resource calendar. This replaces the assumption
`docs/goals/ACTIVE.md` carried since PR #22, that a Microsoft lag is consumed on
the successor's effective calendar, and it is what the plan now resolves
`LagCalendar.SUCCESSOR` to for a Microsoft file.

**Slack is measured on the same calendar a lag is consumed on** — the task's
own or the project's — even when the work was placed on a resource's.
`PlannedActivity` therefore carries a `measure_calendar` beside its scheduling
calendar, and every float is measured in the first. This does not change
ADR-008: the float is still working time and still the smaller of two
readings; it says which calendar that working time is counted on.

**The project start bounds only a task with no predecessors.** A task with a
predecessor is placed by that predecessor alone, even when a lead puts it
before the project start. Work that has begun is bounded by its actual start
instead, as the post-S5 review established.

**The successor of an inactive task is labelled, not ruled.** The edge from an
inactive task is dropped, as before, and the successor is reported on
`Plan.assumed` as `ACTIVITY_SUCCESSOR_OF_INACTIVE`, because the files do not
agree on what Project does with it.

## Evidence

Every count below is taken through `build_plan` and the two passes and pinned
in `tests/test_forward_pass_boiler.py` and `tests/test_backward_pass_boiler.py`.
"Exact" means start and finish both equal to the dates the file stores.

| File | Activities | Exact before | Exact after | First mismatches | Inherited |
|---|---|---|---|---|---|
| BOILER, un-progressed | 451 | 1 | 384 | 8 | 59 |
| KILN | 417 | 36 | 247 | 6 | 164 |
| CALCINER | 1,763 | 260 | 1,645 | 6 | 112 |

A *first mismatch* is a row that differs while every one of its predecessors
agrees; every other difference is inherited from one. So the three files
between them have twenty rows the rules above do not explain, and the rest of
the difference is those twenty rows' descendants.

**The calendar rule.** With it alone, BOILER went from 1 to 278 exact. The
half-hour cluster was the project calendar's 07:30 against the resources'
07:00. The rule is the one the previous engine carried and the forward-pass
slice turned off after sixteen activities lost all working time — those came
from intersecting a task calendar with a resource's on rows the rule says take
the resource's alone.

**The project-start rule.** The twenty-eight-day cluster was a single edge: a
lead of −403,200 tenths of a minute — twenty-eight days — from a one-hour task
at the project start to the two earliest tasks in the file, which the pass had
floored at the project start and so placed four weeks late, with their chains
behind them. BOILER carries fifty-six leaf tasks that start before its project
start, KILN twenty-five and CALCINER a hundred and thirty; all three files
schedule from their start with constraints not honoured, so it is not backward
scheduling.

**The lag rule.** Of the working-time lags on finish-to-start and
start-to-start links in KILN and CALCINER, fifty-seven are explained by some
calendar and every one of the fifty-seven by the successor's task calendar or
the project's; the successor's effective calendar explains three of KILN's ten
hour-format lags and the predecessor's five. Both project calendars are
twenty-four hours, so "project calendar" and "elapsed" cannot be told apart on
this estate, and three leads are explained by nothing measured.

**The slack calendar.** ADR-008's rule, read off Project's own stored dates,
reproduces the stored `TotalSlack` on the task-or-project calendar for 449 of
451, 417 of 417 and 1,763 of 1,763 — and on the resource calendar for 118, 208
and 500. Our own dates, measured the same way, now agree with the stored total
slack on 380 of BOILER's 451 and 1,488 of CALCINER's 1,763, and our late dates
with the stored ones on 409 and 1,572.

**Inactive successors.** Of the active successors of inactive tasks — five in
the un-progressed BOILER, ten in each progressed one, six in KILN — some sit
where the inactive task's own predecessors would put them, some where their
other predecessors do, and some where nothing measured does. On the progressed
BOILER files this is the largest remaining class: they carry twenty-one inactive
rows against the un-progressed nine, and their thirty-four first mismatches are
those successors and the multi-resource rows.

## Consequences

`build_plan(resource_calendars_apply=)` defaults on. `Plan` carries `assumed`
beside `excluded`, so a claim about a schedule names the rows it rests on.
`Network.fingerprint` hashes the measuring calendar.

What remains unexplained is named, per row, and small: the envelope rule for
tasks with several resource calendars, the successor of an inactive task, two
CALCINER rows with the ignore flag and a task calendar, and one KILN row whose
forty-two-hour duration Project placed continuously on a resource calendar that
compiles here as a day shift. KILN's late dates agree on none of its rows
because its project finish is set by a tail that is still inherited-wrong;
that closes with the first mismatches, not separately.

P1-G2 is not met: eight BOILER rows are still unexplained. It is now a list of
rows with a class each, rather than a file that disagrees.
