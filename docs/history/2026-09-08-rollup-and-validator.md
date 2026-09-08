# 2026-09-08 — Summaries roll up, and a result is checked against itself (S6)

The slice the frozen plan describes as "WBS rollup, eligibility re-partition,
independent validator". Two of the three were built; the third turned out to
be already done, and the plan's list for it is superseded.

## A summary's dates are its children's

A summary task carries a duration in the file and it means nothing: Project
derives the span from what sits beneath it, which is why `SCHEDULED_KINDS`
leaves summaries, levels of effort and hammocks out of the network. So the
rollup is not a third traversal but arithmetic over a result the passes have
already produced — the same shape as the float, which is arithmetic over two
passes rather than a pass of its own.

The rule is the obvious one and it is measured. A summary runs from the
earliest start beneath it to the latest finish beneath it, and against the
summary dates the three real files store:

| File | Summaries | Rolled up | Exact |
|---|---|---|---|
| BOILER, un-progressed | 95 | 94 | 75 |
| KILN | 90 | 86 | 36 |
| CALCINER | 219 | 219 | 206 |

The counts are not the evidence. The triage is: **on all three files, every
summary that disagrees has a leaf beneath it whose own dates disagree, and not
one summary is wrong while everything under it is right.** A rollup that
differed with every leaf agreeing would mean Project derives the span some
other way; none does. So the rule is exact wherever the pass beneath it is,
and what remains is the forward pass's residue, already recorded in ADR-010
and already pinned. That property is its own test, because it is the claim
the rule rests on.

`roll_up` takes a tree of identifiers and a mapping of spans, for the reason
the network takes integer coordinates: the corpus declares its cases in hours
and the real files arrive in seconds from an epoch. A branch with nothing
placed beneath it is reported empty rather than given a guessed span, and a
hierarchy that names itself somewhere in its own subtree stops rather than
recurring.

## A result checked against itself

Every other test asks the engine to compute something and compares the answer.
The validator asks whether the relations a finished result *claims* actually
hold — and that difference is the point of the slice. A defect in a pass shows
up in that pass's answer and in anything that recomputes it the same way,
which is how a suite of five hundred passing tests sat above a free float that
overstated safe delay across calendars, a lag inverse that landed after its
own bound, and a constraint one pass applied while the other set it aside.
Every one of those was found by reading the code.

So nothing in it calls `shift_lag`, `earliest_span` or any of the three
passes. It reads dates, durations and calendars and counts working time
between coordinates with `working_between`, whose agreement with the reference
arithmetic the calendar slice established over ten thousand random inputs. If
the passes and the validator agree, they agree by two different routes.

It checks that every row is answered once by all three calculations; that
spans are ordered and consume exactly the work they claim, in both directions,
with completed rows exempt because reported dates are facts and not
placements; that a late span is never earlier than its early one; that total
float is the gap between the two spans on the float calendar; that criticality
agrees with its own float; and that every binding edge is honoured by the
dates it connects, counted rather than shifted.

It reports nothing on any real schedule or on any executable corpus case, and
a test corrupts a sound result seven ways to show each check fires, because a
validator that never fires is worth nothing.

### It refined ADR-008 on the way

ADR-008 records that free float cannot exceed total float when every outgoing
edge is finish-to-start. Measured while writing the check: that holds on one
calendar and **not** across several, with no negative float anywhere. A
predecessor whose own calendar is working where its successor's calendar is a
gap can slip its own working time without moving the successor at all, so it
genuinely holds free float the project does not allow — three such rows in
KILN, five in CALCINER, six in the day-5 candidate. The check therefore asks
only of a network one calendar governs, which is the conformance corpus, and
the caveat is recorded rather than the check dropped.

## The eligibility re-partition, and why it is already done

The plan's list for this half — move `ESTIMATED_DURATION`, `DURATION_FORMAT`,
`MULTIPLE_RESOURCE_CALENDARS` and six more from exclusion to assumption,
replace `INELIGIBLE_PREDECESSOR` with pinning the excluded predecessor to its
source dates so 219 BOILER successors stop cascading out — was written against
the previous engine's forty-six reason codes. None of those codes exists here,
and the cascade it wants removed does not fire: the new engine excludes nine
BOILER rows, twelve KILN, none of CALCINER's and twenty-one of the day-5
candidate's, every one of them inactive but for a single manual KILN leaf, and
`ACTIVITY_PREDECESSOR_NOT_SCHEDULED` reaches no row in the estate at all.

What the gate actually asks — that every leaf gets a disposition — was already
true. So rather than build pin-to-source machinery for one row that has no
successors, the claim is made enforceable: the partition is now a test, of all
four real schedules, and it asks both halves. Nothing falls between scheduled
and excluded, nothing lands in both, no row is excluded twice under two codes,
no assumption names a row the plan did not schedule, and the same holds for
the relationships. A count of dispositioned rows can agree with the leaf count
while the answer underneath it is incoherent; this cannot.
