# 2026-09-08 — The calculation, stored and shown (PL13)

The first slice of this phase whose output a person looks at. Everything before
it was answerable only through a test or the CLI: the engine produced dates, the
projection assembled them, the database held them, and nothing put them in front
of anyone. The resequencing of 2026-09-08 (ADR-011) exists to close that gap
before the interchange work, on the review's argument that a product loop no one
has run cannot be steered.

## What the page had to answer

Not "what does the engine say", which the tests already ask, but the question an
estimator asks of any schedule tool: **does it agree with what I gave it, and
where it does not, why not**.

So a row carries both sets of dates side by side. The imported dates are read
off the stored document rather than copied into the result table, because a
stored copy of what the file said would be a third place for it to drift from,
and the whole point of the canonical version is that there is one. On the
un-progressed BOILER snapshot the page compares 451 placed rows against their
source dates and 384 agree, which is the forward pass's own figure arriving
unchanged at the reader rather than a second measurement of it. On the day-5
candidate it is 444 and 254, and the difference is progress: the rows that
disagree are the ones ADR-009's rules move, and they carry the progress state
and the placement reason that say so.

A row the plan would not schedule shows its code and no dates at all. A summary
shows its rolled-up span, and a branch with nothing beneath it is shown as a
branch with no span rather than dropped from the page, because "nothing was
calculated here" and "this is not in the file" are different answers and a
reader cannot tell them apart from an absence.

## Reading through the check rather than around it

The first version of the route read the three tables and rendered what came
back. That is one integrity guarantee short of the one the version envelope
already has: a schedule version re-derives its hash from the stored document on
every load, so bytes that do not hash to what they claim are refused rather than
served. A calculation could not borrow that guarantee, because its fingerprint
covers rows in two other tables and nothing reassembled them.

So the page reads through a loader that takes the header and both row sets
together, rebuilds the result, recomputes the fingerprint and refuses a
mismatch. An edited row is now a refusal instead of an answer. The rebuild reads
every engine profile out of the stored header rather than defaulting to the
current constants, because a default that agreed with today's code would hide
exactly the case worth catching — the rules changing underneath a stored answer.

## The guards the flow needed

Three of them, none interesting on their own and all of them the difference
between a demo and something that can be left running.

A parse or validation failure becomes a coded failed import batch, not a stack
trace: the operator gets told which file and why, and the failure is recorded
where the successful imports are.

Uploads are bounded, and the bound is enforced while reading rather than after,
so an oversized body is refused instead of buffered.

One stored document that fails its hash check quarantines its own project. Boot
loads every project's head, and a boot that refused entirely because one of them
was bad would hide which one; that project's routes report the failure and the
others serve.

## What is not here

No editing. The page is read-only, and the loop the phase gate asks for — change
a duration, watch the successors move, reset — is the next slice. This one puts
the calculated schedule where it can be looked at, which is the precondition for
believing anything about the one after it.
