# ADR-008: A float is working time, and a total float is the smaller of two

Status: accepted, 2026-09-05

## Context

The backward pass produces a late start and a late finish for every activity.
Turning those into a float needs three answers the pass itself does not supply,
and each of them has more than one defensible reading.

**What unit is a float in?** A float is a difference between two coordinates,
and the difference can be read as elapsed time or as working time on the
activity's calendar. Every other duration in the engine is working time, so the
argument from consistency says working time — but an argument is not evidence,
and a schedule on a five-day calendar makes the two readings differ by every
weekend that falls in the gap.

**Which difference is the total float?** An activity's early span and its late
span can consume a calendar's gaps differently, so `late start − early start`
and `late finish − early finish` are not the same number. Textbook CPM treats
them as interchangeable because it is written for continuous time. The semantic
conformance corpus cannot settle it either: both its float cases are declared on
a 24×7 calendar, where all the readings coincide.

**When is an activity critical?** `total float <= threshold` is uncontroversial;
what the threshold is, is not. Microsoft Project files carry a
`CriticalSlackLimit` as a whole number of days, and a day is only a number of
seconds once you decide whether it is a calendar day or a working one. The
importer read the field and dropped it, which `docs/goals/ACTIVE.md` recorded as
owed to this slice.

All three are questions about what an existing tool already does, so all three
were asked of the real schedules rather than answered from first principles.

## Decision

**A float is working time on the activity's own calendar**, signed, so that a
late date before an early one reports as negative float rather than as zero.

**A total float is the smaller of the start float and the finish float.** Both
components are kept on the result rather than collapsed, because when they
disagree it means the two spans straddle a calendar gap differently, and that is
a fact about the schedule worth being able to see.

**Free float is measured against the successors' early dates** on the same
calendar and by the same edge rules the forward pass used, and against the
project late finish for an activity with no successors.

**Criticality is `total float <= critical_float_threshold_seconds`**, and
`CriticalSlackLimit` converts to that threshold as **days of the project's own
`MinutesPerDay`** — working days, not calendar days.

## Evidence

Every measurement below is taken from Microsoft Project's **own** stored early
and late dates, not from ours. That matters: our forward pass does not yet
reproduce the dates Project stored for these files, so a measurement that
started from our dates would be testing that disagreement instead of the rule.
`tests/test_backward_pass_boiler.py` pins every count.

On the un-progressed BOILER snapshot, over its 451 schedulable activities, each
reading reproduces the `TotalSlack` Project stored for this many of them:

| Reading | Reproduces |
|---|---|
| elapsed, `late finish − early finish` | 20 |
| working time, start side | 316 |
| working time, finish side | 361 |
| working time, **the smaller of the two** | **449** |

Neither component alone is the rule. The smaller of the two is, and it holds
across the estate: 417 of 417 on KILN and 1,763 of 1,763 on CALCINER, the
largest real schedule available. Two BOILER rows are not explained by it and are
counted rather than absorbed.

The free-float rule reproduces the stored `FreeSlack` for 448 of 451 on BOILER,
407 of 417 on KILN and 1,730 of 1,763 on CALCINER.

CALCINER is the one file in the estate that declares a non-zero
`CriticalSlackLimit`: six, against a 480-minute working day. At the working-day
reading — 172,800 seconds — `total float <= threshold` reproduces its `Critical`
flag for all 1,763 activities. Ignoring the limit reproduces 1,478 and reading
the six as calendar days reproduces 1,623. The file's own flags bracket the true
threshold to somewhere in [156,600, 201,600) seconds, which contains the
working-day reading and excludes both alternatives.

The criticality rule itself is confirmed the same way: on the un-progressed
BOILER snapshot, `stored total slack <= 0` equals the `Critical` flag Project
stored for every activity in the file.

## Consequences

**Free float can exceed total float, and that is not a defect.** A
start-to-finish successor does not care when its predecessor ends, so the
predecessor can slip past the project finish — spending total float — without
moving anything downstream. Two of the estate's schedules store a `FreeSlack`
above their own `TotalSlack` on a handful of rows, so a rule forbidding it would
contradict the oracle. The invariant is asserted for finish-to-start logic only.

**The corpus cannot regress these decisions.** Both float cases are on a
continuous calendar, where all three readings agree. Only the file oracle
distinguishes them, so the counts above are the regression test, which is why
they are pinned rather than described.

**Criticality on a progressed schedule is not settled by this ADR.** The rule
reproduces the un-progressed snapshot exactly and the progressed ones do not
follow it: a complete activity is not critical whatever its slack. That belongs
to the status date and is the next slice's.

**The per-activity projection table that ADR-006 deferred is now unblocked**
and is not built here. Its columns have meanings and a result type to mirror as
of this decision, which was ADR-006's condition; it is carried as its own
roadmap row rather than folded into an engine slice.
