# 2026-09-08 — The two passes and the float agree on what they calculate (C2)

The second correction slice of the resequenced Phase 1 (ADR-011), answering
findings F06, F12, F13 and F14 of the 2026-09-07 comprehensive review. None of
the four is a disagreement about a scheduling rule. Each is one calculation
reading an edge, a policy or a calendar differently from the calculation beside
it, which is why a suite that passes says nothing about them.

## Free float was measuring the wrong movement (F06)

The float shifted the lag forward from the predecessor and measured whatever
gap was left on the predecessor's own calendar. That assumes the two calendars
advance together, and across a broken one they do not. The review's
counterexample reproduces exactly: a predecessor on 0-5, 15-25, 30-100 with a
three-unit lag on a continuous calendar and a successor held at twenty reports
five units of free float against a total float of two. Delaying the
predecessor by all five moves the successor to 23; only two were ever free.

The successor's bound is now carried *back* over the edge — the inverse of the
shift the forward pass made — and the movement measured from the predecessor's
own coordinate to the latest one that still lands on time. The counterexample
reports two, and a second test re-places the predecessor by exactly the
reported slack and by one more, to check the number means what it says.

The same rule understates as badly as it overstates, which came out of an
older test whose expectation had been written under it: a predecessor whose lag
cannot begin to be consumed until the successor's calendar opens really can
slip ninety units before the successor moves, where the shift-first reading
reported none. Against the files' own stored `FreeSlack` the corrected rule
agrees on more rows, not fewer.

## The lag inverse was not an inverse (F14)

`unshift_lag` ran the arithmetic the other way, which is only an inverse where
the calendar is continuous. Across two calendars of the estate's shape there
are sixty-six anchors where walking a negative lag forward and then back lands
*after* the bound the caller gave — so the backward pass was setting late dates
the schedule cannot honour, and the corrected free float would have read the
same coordinates.

It is now defined by the inequality it has to satisfy: the greatest coordinate
whose lag lands at or before the anchor, found by expanding the upper end until
it stops landing in time and then halving. Verified over four calendars and
both signs of lag: no overshoot, and no later coordinate that also fits.

**This supersedes a decision.** The post-S5 review rejected exactly this
correction with a measurement — the round-trip artefact was always zero working
time, so it could not reach a float. That held for the arithmetic as it stood
and stopped holding when the free float began reading the same function.
`tests/test_backward_pass.py` records the supersession where the old bound was
pinned.

## An edge the policy had discarded refused the schedule (F12)

Whether a predecessor holds its successor at all is the progress policy's
question, and it was being asked after the predecessor's bounds had been
computed. Under progress override an in-progress successor's remaining work
runs from the status date and no predecessor holds it, but a lag that leaves
the calendar had already refused the whole schedule over a coordinate the
policy discarded. The review's case — continuous horizon 0-100, an eighty-unit
predecessor, a successor started at ten with one unit left, status date fifty,
a thirty-unit lag — now places both rows.

Completed work is the same defect one state along: a complete activity is its
two actual dates and reads no bound at all, so computing its predecessors'
bounds could only refuse a schedule over a coordinate nothing looks at.

Retained logic still refuses that network, and should: that policy does read
the bound, and the remaining work genuinely cannot start inside the horizon.
The test says so, so the refusal is not mistaken for the defect.

## Two passes, two answers about one constraint (F13)

The forward pass places work already under way on what happened and records
every constraint it carries as not applied — an actual date is a fact and a
constraint is an intention. The backward pass applied must-start-on and
must-finish-on to the same rows. An activity started at one with five units
left, a status date of fifty and a must-start-on of twenty had its remaining
work placed at 50-55 going forward and pinned at 20-25 coming back: minus
thirty of total float, invented entirely by the two passes disagreeing about a
constraint neither of them should apply. Both defer it now, and both say so.

## Withdrawn: where an elapsed span starts

C1 recorded a measured rule owed to this slice — that Microsoft Project starts
an elapsed span at the next working moment on the activity's calendar and then
counts clock time — on the evidence that BOILER's two elapsed rows land six and
a half hours before the dates the file stores, exactly its resource calendar's
opening time. It was implemented here and changed nothing, because those rows'
effective calendar is twenty-four hours: there is no working moment to snap to.

Looking again at where the offset comes from: both rows start exactly at their
predecessor's computed finish, and it is the *predecessors* whose stored
finishes are 06:30 and 08:30 against the 00:00 and 02:00 computed for them. The
six and a half hours are inherited, not introduced. The mechanism was removed.

What the files do corroborate is the half of the rule C1 shipped. On both
BOILER rows and both CALCINER rows the span Project stored — its own finish
minus its own start — equals the elapsed duration exactly, so an elapsed span
really is clock time and not working time. Where such a span begins, relative
to logic rather than to a predecessor that already agrees, remains unmeasured,
and `ACTIVITY_DURATION_ELAPSED` stays a labelled assumption.

This is the fourth claim in this estate to be withdrawn after measurement
rather than shipped.
