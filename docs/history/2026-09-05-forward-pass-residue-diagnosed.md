# 2026-09-05 — The forward-pass residue, diagnosed

The forward pass agreed with Microsoft Project on one BOILER activity in
four hundred and fifty-one since 2026-09-03, recorded undiagnosed rather than
guessed at. This session was the diagnosis: nothing written down before it
was measured, and three of the four causes were not the ones suspected.
The decisions are ADR-010; this is how they were reached.

## Read the file, not the importer

The first measurement was of the file itself, with no engine in the way:
project settings, constraint types, inactive rows, links touching summaries,
the starts of tasks with no predecessors, and whether the stored dates obey
their own links. They do — no finish-to-start link in BOILER has a successor
starting before its bound — and the root tasks start at the project start on
two different day-starts, 07:00 and 07:30. All three real files schedule from
their start with constraints not honoured. Fifty-six leaf tasks start before
BOILER's project start with no constraint and no manual flag, and the earliest
hangs off a one-hour task at the project start with a lead of −403,200 tenths
of a minute.

That lead is twenty-eight days. The thirty-eight-row cluster at exactly 672
hours was one edge the pass had refused to let reach back past the project
start.

## The calendar was the resources' all along

`IgnoreResourceCalendar` is clear on 548 of BOILER's 555 tasks and 508 of them
name no calendar of their own. Project schedules such a task on its resource's
calendar. The forward-pass slice had turned resource calendars off after
intersecting them with task calendars emptied sixteen rows; the rule it needed
was not intersection but replacement for a task with no calendar of its own.
With that rule alone BOILER went from 1 exact match to 278, and the forty-nine
rows exactly half an hour out were the project calendar's 07:30 against the
resources' 07:00.

The previous engine, `sto.legacy`, carried this rule. It was lost in the move
to `build_plan` and the loss was recorded as a decision rather than noticed as
one.

## The project start is not a floor

A floor at the actual start, from the post-S5 review, had already shown the
shape: the one in-progress row started five weeks before the project start and
Project placed it from where it started. The same is true of unstarted work
with a predecessor. The base the predecessors raise is now the project start
only for a task with none. BOILER: 278 to 334.

## First mismatches, not mismatches

From there every remaining difference was classified as *first* — every
predecessor agrees — or *inherited*. BOILER had eleven first mismatches and a
hundred and six inherited from them, which is the whole picture of the
remaining residue: a few local causes with long cascades. KILN had eleven
first and three hundred and fifty-five inherited.

Eight of BOILER's eleven were tasks whose resources are on several calendars.
Project's stored task span is the envelope of its stored assignment spans on
every such row in BOILER and KILN and all but three of CALCINER's nine hundred
and seventy-nine. The union of the calendars stands in for that and is
recorded per row as an assumption. BOILER: 334 to 384; CALCINER: 525 to 1,602.

## The lag calendar, by lag format

KILN was still at fifty-two. Its lagged links, read off stored dates with no
pass at all, said that hour-format lags were consumed on neither the
successor's nor the predecessor's effective calendar but on the project's,
and its one day-format lag on the successor's own task calendar. One rule
covers both: the successor's task calendar when it has one, else the
project's. That explained every link any hypothesis explained — fifty-seven
across KILN and CALCINER — and moved KILN to 245. The assumption `ACTIVE.md`
had carried since PR #22 is falsified and replaced.

## The slack calendar, found by a test that broke

Turning the calendar rule on broke ADR-008's tests: the smaller-of-two rule,
read off Project's own stored dates, reproduced the stored `TotalSlack` for
118 rows instead of 449. The rule was right; the calendar it was measured on
had changed. Measured on the task-or-project calendar again it is 449, 417 and
1,763 of 1,763, and on the resource calendar 118, 208 and 500. So Project
places work on the resource's calendar and measures slack on the task's — the
same calendar it consumes a lag on. `PlannedActivity` now carries the two
apart, and our own float agrees with the stored one on 380 of BOILER's rows
where it agreed on 19.

## What the successors of inactive tasks do

The three BOILER first mismatches that were not multi-resource rows were all
successors of inactive tasks. Treating an inactive task as a zero-duration
pass-through was tried and made BOILER worse. Read off stored dates, the
successors follow no single rule: on the un-progressed file three of five sit
where the inactive task's own predecessors would put them and two where their
other predecessors do; on the progressed files five of ten sit where nothing
measured puts them. They are labelled `ACTIVITY_SUCCESSOR_OF_INACTIVE` and
counted, which is what makes the progressed files' thirty-four first
mismatches a list rather than a mystery.

## Where it stands

| File | Exact before | Exact after | Late dates | Total float | First mismatches |
|---|---|---|---|---|---|
| BOILER | 1 | 384 of 451 | 409 | 380 | 8 |
| KILN | 36 | 247 of 417 | 0 | 4 | 6 |
| CALCINER | 260 | 1,645 of 1,763 | 1,572 | 1,488 | 6 |

Twenty first mismatches across three files, each in a named class. P1-G2 is
still open — eight BOILER rows are unexplained — but it is now a list of rows.

## Rejected

Backward scheduling (`ScheduleFromStart` is set on every file). A stale
tooling-written file (the stored dates obey their own links, and the untouched
source gives identical counts). Inactive tasks as pass-throughs. Seeding the
project start from the earliest task, which the forward-pass slice had already
found helps one file and harms another; the lead explains why.
