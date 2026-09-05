# 2026-09-03 — The forward pass, and what the real files said about it

S3, the engine half. All four relationship types with signed lag, over the
calendars S2 compiled. What was learned doing it:

## The engine takes coordinates, not a schedule

`sto.core.engine.network` carries integer coordinates and compiled intervals
and no policy at all. That was done for testability and turned out to matter
for a better reason: the conformance corpus is declared in **hours** from an
origin and this repository works in **seconds** from an epoch, and because the
pass never learns which, the corpus drives the real engine directly instead of
a reimplementation of it. Thirty-eight of the fifty cases are answerable by a
forward pass alone and all thirty-eight pass on dates and project finish.

`sto.core.engine.plan` is where every policy decision was pushed: which
calendar an activity works to, which calendar a lag is consumed on, which rows
are scheduled at all.

## Zero lag must not snap, because placement already does

Lag and placement both want to move a coordinate onto working time, and doing
it in both places moves a successor a whole interval too far. The rule that
holds is the corpus's: zero lag returns its anchor untouched even inside a gap,
and only placement snaps. A four-hour activity on an eight-hour day finishes at
noon — the morning interval's *exclusive* edge, not working time — and its
FS successor starts at one, not at two.

## Milestones had two right answers, so the model chose

A zero-duration activity is a coordinate, not a span. The previous engine leaves
it exactly on its predecessor's finish; `earliest_span` snaps it to the next
working coordinate. Both are defensible and they disagree on precisely the case
above, where a predecessor finishes on an edge. `MilestoneSnapPolicy` already
existed in the canonical model for this question — its docstring says Microsoft
Project leaves it and the reference semantics snap it — so the pass reads the
policy instead of picking. Neither behaviour is assumed and both are tested.

## The corpus's driving relationships are curated, not exhaustive

An equality assertion against `expected.driving_relationships` failed on two
cases. It was the assertion that was wrong, not the pass: SEM-NET-015 declares
only `R2` because the case is about C controlling the project finish, though
`R1` is equally the only thing placing B, and the corpus's own validator asks
only that each relationship it lists genuinely governs. The check is
containment.

## The file oracle found a bug that no unit test would have

Intersecting an activity's calendar with **every** assigned resource's calendar
left sixteen BOILER activities with no working time at all, silently
unschedulable. Two shift calendars are routinely disjoint. Restricting it to a
single distinct resource calendar did not fix it either — those sixteen carry
*one* resource whose calendar is disjoint from the task's.

Microsoft Project has a task-level `IgnoreResourceCalendar` flag and its own
rule for which calendar wins, and neither is measured here. So
`build_plan(resource_calendars_apply=...)` defaults to off for a Microsoft file
and the question is named rather than answered wrongly. With it off, every
activity in the file that is active schedules.

## What the forward pass does not yet reproduce, stated plainly

On `boiler-before-no-progress.xml`, 451 of 460 activities schedule — the nine
that do not are inactive, and the fifteen dropped edges lost an endpoint to
them. Against the dates Microsoft Project itself stored in the file, **one**
matches exactly.

That is not explained yet, and it is recorded rather than diagnosed, because
twice before a confident cause has been written down here that the evidence did
not support. What has been measured, and what it rules out:

- The file carries **no constraint of any kind**: all 460 tasks are ASAP with no
  constraint date, no deadline, no manual placement and no levelling delay, and
  all 600 links are FS with six elapsed lags. So the difference is not a
  constraint this pass declined to apply. A test pins this.
- The file's `<StartDate>` is `2026-09-13T19:00`, but 56 tasks start before it
  and the earliest starts `2026-08-17T07:00` — 27.5 days earlier. The largest
  cluster of differences is exactly 672 hours, which is 28 days. Seeding from
  the earliest task instead raises exact matches from 1 to 38 and flips the
  bulk of the differences to roughly minus 672 hours, so the seed is part of it
  and is not all of it. On KILN the same substitution makes matters worse (29
  exact to 2), so "seed from the earliest task" is not the rule either.
- A cluster of 49 differences is exactly half an hour, which no hypothesis here
  accounts for.

The next slices own this. The P1 gate asks that no difference be UNEXPLAINED
across start, finish, late dates, float and criticality, which is the backward
pass and the status date as much as this one; a forward pass alone was never
going to close it. What this slice can say is bounded and is said: the
semantics are proven against the corpus, and the real-file agreement is not
claimed.

## Scope left where it belongs

The corpus is still read from a `dezrobbo1/PM-Software` clone through
`STO_PM_SOFTWARE_DIR`. Copying it in with SHA-256 pins — which is what makes
`PR-conformance-suite` live — is a separate outcome and is not in this change.
Constraints that cannot pull an early date earlier (ALAP, SNLT, FNLT) are
carried to the result rather than treated as ASAP, so the backward pass
receives them instead of rediscovering them.
