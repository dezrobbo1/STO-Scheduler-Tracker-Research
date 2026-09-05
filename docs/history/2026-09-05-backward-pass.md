# 2026-09-05 — The backward pass, and three questions the files answered

S4. Latest dates, float and criticality, over the forward pass S3 built. The
pass itself was the easy half; the three decisions around it were not, and all
three were settled by measurement rather than by argument. What was learned:

## The mirror is where the bugs are, so the tests are relations, not values

`sto.core.engine.backward` is `forward` transposed: the four relationship types
read the opposite end of the opposite activity, `latest_span` mirrors
`earliest_span`, and lag is walked back rather than forward. Code shaped like
that is wrong in one direction only, and a test that checks a value in the
wrong direction agrees with it.

So most of the suite states a *relation between the two passes* and checks it
over generated networks: every late span consumes the working time its early
span did; nothing has negative float without a late constraint; the two runs
fingerprint identically. Two real bugs came out of exactly those tests and
neither would have been caught by more hand cases.

**A milestone is placed, not ended.** Snapping a milestone backwards used
`prev_working`, which answers for *finishes* — a finish lies in `(start,
finish]` of an interval and a start lies in `[start, finish)`, so the two edges
answer oppositely. A milestone snapped back off the front of the very interval
the forward pass had snapped it into. The fix named the missing function:
`prev_working_start` is the true mirror of `next_working`, and `prev_working` is
its finish-side sibling rather than its opposite.

**A late date before the project start is an answer, not an error.** The floor
was the project start, mirroring the forward pass's horizon. That is the wrong
mirror. A forward pass running past the horizon has nowhere to put the activity
because the calendar stops; a backward pass reaching below the project start has
somewhere to put it and is telling you the schedule is over-committed. Refusing
turns the report into a crash. The floor is now where the **calendar** runs out,
and an unmeetable constraint produces negative float.

## What unit is a float in? The files said working time, loudly

Both readings are defensible in the abstract and the conformance corpus cannot
separate them — both its float cases are declared on a 24×7 calendar, where they
coincide. The real schedules have weekends.

Asked against Microsoft Project's *own* stored early and late dates, so that our
forward pass's disagreement could not contaminate the answer: over the
un-progressed BOILER snapshot's 451 schedulable activities, the working-time
reading reproduces the `TotalSlack` Project stored for 361 of them and the
elapsed reading for 20. That is not a close call.

## Which difference is the total float? Neither — the smaller of them

The same measurement showed that neither component reproduces the file on its
own: the start side gets 316 and the finish side 361. Taking the smaller of the
two gets 449 of 451, and then 417 of 417 on KILN and 1,763 of 1,763 on CALCINER
— 2,631 activities across three schedules, two of which the rule does not
explain, both of them counted. *(This paragraph originally said 3,076 across
four with sixteen unexplained; the pinned assertions in
`tests/test_backward_pass_boiler.py` say otherwise and the automated review of
PR #31 caught it. Corrected 2026-09-05.)*

It is obvious in hindsight and invisible in continuous time: an activity's early
and late spans can straddle a calendar's gaps differently, so the two floats are
not the same number, and Project takes the one that binds. Both components stay
on the result rather than being collapsed into the minimum, because when they
disagree that is a fact about the schedule.

The free-float rule was checked the same way and reproduces the stored
`FreeSlack` for 448 of 451, 407 of 417 and 1,730 of 1,763.

## Free float above total float is real, and Project does it too

A generated case tripped the invariant `free <= total`, which is a textbook
theorem. The theorem is finish-to-start only. A start-to-finish successor does
not care when its predecessor *ends*, so the predecessor can slip past the
project finish — spending total float — without moving anything downstream.

Rather than argue it, the files were asked: two of the estate's schedules store
a `FreeSlack` above their own `TotalSlack` on a handful of rows. Forbidding it
would have contradicted the oracle. The invariant is now asserted for
finish-to-start logic and the start-to-finish case has a test of its own saying
why it is allowed.

## The criticality threshold was measurable after all

`ProjectSettings.critical_float_threshold_seconds` had been carried since PR #22
as a field the importer read and dropped, on the assumption that no file in the
estate set it. That was true of BOILER and false of the estate: **CALCINER
declares a `CriticalSlackLimit` of six**, against a 480-minute working day.

So the conversion is evidence rather than an assumption. Read as working days —
172,800 seconds — `total float <= threshold` reproduces CALCINER's `Critical`
flag for all 1,763 of its activities. Ignoring the limit reproduces 1,478;
reading the six as calendar days reproduces 1,623. The file's own flags bracket
the threshold to [156,600, 201,600) seconds, which admits the working-day
reading and excludes both others. Recorded as ADR-008.

The criticality *rule* is confirmed the same way: on the un-progressed snapshot,
`stored total slack <= 0` is exactly the `Critical` flag Project stored, for
every activity in the file.

## What is still not claimed

Our own late dates reproduce Project's on **none** of the 451, and our own total
float on 19. That is inherited, not new: the forward pass agrees with Project on
one activity of this file for reasons recorded undiagnosed in
`docs/history/2026-09-03-forward-pass.md`, and a backward pass over early dates
that are wrong produces late dates wrong in the same way.

One number in that picture is worth keeping. Our **free** float agrees on 351 of
451, against 19 for total float. Free float is local — the gap between an
activity and its immediate successors — and total float is measured against the
project finish. A local quantity surviving where a global one does not is
consistent with the whole schedule sitting in the wrong place while its internal
logic is right, which is what the forward-pass entry suspected and could not
show. Both counts are pinned in `tests/test_backward_pass_boiler.py`, so closing
the forward-pass difference will fail those assertions and force this entry to
be corrected deliberately.

## Housekeeping

The corpus-to-network mapping moved to `tests/conformance_fixture.py` so the
forward and float cases are held to the corpus through one mapping rather than
two. `KILN` and `CALCINER` now have environment variables of their own —
`STO_KILN` and `STO_CALCINER` — because the float rule's evidence rests on them
and `STO_REQUIRE_BOILER=1` should fail on their absence too.

The per-activity projection table ADR-006 deferred is now unblocked: its columns
have meanings and a result type to mirror, which was ADR-006's stated condition.
It is not built here — it is persistence work, not engine work, and no P1 gate
criterion asks for it — and is carried as its own roadmap row so the commitment
stays visible.
