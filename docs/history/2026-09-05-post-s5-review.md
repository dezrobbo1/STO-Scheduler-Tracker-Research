# 2026-09-05 — What the review after S5 found, and the row that settled it

A review pass over the two slices merged that day, before S6 started. Two
things were wrong with how they had been merged, one thing was wrong in the
engine, and answering the reviews turned up a rule the estate's only in-progress
row had been able to settle all along.

## Two pull requests went past their reviews

`AGENTS.md` says the first automated review pass is answered in full. PR #31
received six findings ten minutes after it opened and merged thirty-two minutes
later with no further commit and no comment classifying them; PR #32 merged
eight seconds before its review started, and that review found five more. None
of the eleven had been read. They are answered here, and the rule stands as
written: it is a rule about us, not about the reviewer.

One of the six was a false number in a history entry — the float rule's
evidence stated as 3,076 activities across four schedules with sixteen
unexplained, where the pinned assertions say 2,631 across three with two. The
arithmetic in ADR-008 was right and the prose beside it was not. Corrected in
place with a note, because a history entry that is silently edited is no longer
a history.

## Remaining work was placed before the work began

The forward pass floored an in-progress activity's remaining span at its logic
and, when there was one, the status date. Neither is guaranteed to lie after the
actual start. Both this review and PR #32's found it independently: with no
status date, an activity begun at 500 with ten units left was placed from 0 and
forecast to finish at 10, and its successors were placed before it had started.

The first fix — a floor at the actual start — was measured against the day-5
candidate and **changed nothing**. Its one in-progress row starts five weeks
before the project start, so the project start was the bound holding it, and a
floor at the actual start is below that. Project's own answer for the row is
its remaining eight hours consumed from the actual start on the task calendar:
two hours to the end of that Friday and six on the Monday, finishing at 13:30,
which is what the file stores. The project start is a bound on where unstarted
work may begin, and work that has begun is past it. So for started work the
actual start replaces the project start as the base the predecessors raise, and
the row now reproduces the file exactly.

The row had been able to say this since S5. The file-oracle test asserted the
finish of completed rows and skipped it for the row under way, so a forecast
three weeks late passed. It asserts both now, and pins the row separately with
its zero actual duration and absent resume date — the floor is the actual start
and not the end of the work already done, and that distinction is not measured
until a row that has consumed some of its duration arrives.

## The policy has to reach the backward pass

Under progress override the forward pass releases a predecessor's hold over an
in-progress successor's remaining work. The backward pass still walked that
edge, so a two-hundred-unit predecessor of work continuing from the status date
was bounded to finish before it could, and the pass refused — floor exceeded —
a schedule the forward pass had just answered. `relationship_binds` now decides
once which edges the policy releases; the backward pass skips them, reports
them, and the free float drops them too.

## Refusals and guards

Work that has started with no remaining duration reported is refused rather
than given its whole duration again — every real file and every corpus case
that reports a start reports what is left. A constraint on work that has
started is carried on `deferred_constraints` rather than dropped, because what
it should do to the remaining span is unmeasured. A project late finish past
the compiled horizon is refused rather than snapped onto the last interval. The
two passes and the float are bound to the network by `Network.fingerprint`, so
old early dates cannot pair with new late ones. The float's two refusals carry
codes like every other refusal in the engine. The forward fingerprint carries
the progress state and the criticality fingerprint the two component floats,
so the cross-process digest covers both; the profiles moved to
`sto-forward-pass-v3`, `sto-backward-pass-v2` and `sto-criticality-v2`.

## A finding measured and not taken

The negative-lag finding said `add_working` is not the inverse of
`sub_working` across a gap, and so the backward pass understates late dates.
Measured over the broken calendar and, separately, over twenty thousand random
trials on BOILER's shape: from every coordinate a placed start or finish can
occupy, walking a lag back and forward again returns to the anchor, for both
signs of lag. The round trip departs only from a coordinate *inside* a gap —
which only a non-snapped milestone can occupy — and then by zero working time,
which is what a float is measured in. That bound is pinned as a test rather
than the code changed, because a correction for an artefact that cannot reach
a float is a new way for a real schedule to behave differently for nothing.

## Not done here

The forward pass still agrees with Project's stored dates on one activity of
the un-progressed BOILER snapshot, undiagnosed since S3. Gate criteria P1-G2
and P1-G3 rest on it, and S6 is budgeted for rollup, eligibility and the
validator, not for that diagnosis. It needs its own time before S6, and one
cheap hypothesis is already out: all three real files schedule from their
start with constraints not honoured.
