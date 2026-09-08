# 2026-09-07 — The reviews of PR #33 and PR #34, answered on one branch

Eight findings between two reviews, none of them read when they arrived. PR
#33 — the answer to the S4 and S5 reviews — merged at 15:24 on 2026-09-05 and
its review landed at 15:29, three findings on a pull request that no longer
had a branch to fix them on. PR #34, the forward-pass residue diagnosis,
received five on its open branch an hour later. `AGENTS.md` says the first
pass is answered in full; the rule was met by carrying #33's three onto #34's
branch, where six of the eight touch the same three files.

Each finding was checked against the code before it was acted on, per the
standing note that grade has not tracked severity here. All eight held.

## The two passes could run under different policies

The forward pass takes a progress policy; the backward pass took one too, with
the same default. Nothing bound them. `Network.fingerprint` binds the two
passes to one network but the policy is not a fact about the network, and the
corpus determinism worker called the backward pass without a policy for every
case — so SEM-STA-044, the one override case, had its early dates computed
under override and its late dates under retained logic, and its predecessor
reported total float −2 where the consistent answer is 0. The digest that is
compared across three interpreters attested that.

The policy now travels on `ForwardPass.progress_policy`. The backward pass
reads it from there; a caller may name it again, and naming a different one is
refused as `SCHEDULE_POLICY_MISMATCH` before an edge is walked. The earlier
test that reproduced the walked-edge refusal (`SCHEDULE_FLOOR_EXCEEDED`) now
asserts the refusal by name instead — the defect is caught earlier, not
differently. The worker's digest moved, which is the point: it was wrong.

The backward fingerprint hashed late times and the project late finish. Under
override a redundant edge — one the status date had already floored the
successor past — is released without moving a late date, and the digest could
neither attest that nor notice the pass ceasing to report it. The released
edge ids are in the hash; profile `sto-backward-pass-v3`.

## The free float read two edges differently from the forward pass

Free float substitutes the *remaining* start for an in-progress activity's
early start, because that is what an edge into it bounds. The substitution was
applied to the whole map, so it also moved the anchor of an edge *out of* such
work: an SS edge the forward pass anchored on the actual start was measured
from where the remaining work resumes. An activity begun at 0, resuming at 10,
with a zero-lag SS successor that started at 0 reported −10 of free float for
being exactly on time. The substitution is now successor-side only.

The same function fell back, for an edge with no lag calendar, to the
successor's *measuring* calendar. Both passes fall back to its *scheduling*
calendar, and since ADR-010 the two are routinely different shifts. On a real
file this could not fire — the plan sets an edge's lag calendar to `None` only
for zero lag — and the corpus declares no measuring calendar, which is why no
test had reached it. A directly built network reaches it: a lag consumed on a
calendar that opens at 100 measured on a continuous one reported ninety units
of slack the predecessor does not have. The float now carries the two calendar
maps apart, as the plan does.

## The driver replay floored at the project start

PR #34 let a task with predecessors be placed before the project start — the
rule that closed the twenty-eight-day cluster. `_driver()` decides whether the
finish bound moved a task by placing it again without that bound, and it
substituted the project start. For a task placed before the project start by
two leads, the trial span landed at the project start, past the real finish
bound, and the start edge was credited. Dates were right; the reported driver
was not. The replay now floors where `_bounds()` floored — the calendar's
start for a task with predecessors, the actual start for started work.

## Two labels, one missing and one over-counted

ADR-010 and the PR said the project-calendar lag choice "is labelled". It was
labelled in prose. The plan resolved `LagCalendar.SUCCESSOR` to the project
calendar for a successor with no task calendar and recorded nothing, so an
evidence consumer reading `Plan.assumed` would take the result as measured. It
is now `RELATIONSHIP_LAG_ON_PROJECT_CALENDAR`, one per edge with a non-zero
lag: 14 in KILN, 41 in CALCINER, none in BOILER, which carries no non-zero
working lag at all — its six non-zero lags are elapsed leads, consumed on the
continuous calendar and never labelled.

`ACTIVITY_SUCCESSOR_OF_INACTIVE` was appended per edge from an inactive task,
and `assumed_by_code()` says it counts rows. A successor with two inactive
predecessors counted twice. Labelled once now. BOILER's pinned count of five
did not move — no BOILER successor has two inactive predecessors — which is
why the pin had not caught it.

## A valid spelling of a flag

MSPDI's `IgnoreResourceCalendar` is `xsd:boolean`; the importer preserves its
text as written and the migration accepted only `"1"`. A file writing `true`
would have lost the flag silently and been scheduled on its resource calendar.
Every file in the estate writes `0` or `1` — 5,601 and 244 occurrences — so no
real schedule was affected, and the legacy calculator at least refused other
spellings. Both spellings are recognised now, as a guard the repository could
carry and did not.

## What did not move

BOILER 384 of 451, KILN 247 of 417, CALCINER 1,645 of 1,763; late dates and
total float as pinned. The forward fingerprint profile is unchanged — no early
date or state moved — and the criticality profile is unchanged because its
inputs are the corrected passes. Twelve tests in
`tests/test_post_residue_review.py`, each shown to fail on the code as it was.

## The second pass, answered 2026-09-08

The reviewer ran again on the commit above and raised five findings; the
comprehensive repository review of 2026-09-07 reproduced all five and asked
that they be corrected in this PR before it merged. Each is fixed with one
test in `tests/test_post_residue_review.py`, and no agreement count moved.

**An explicit lag policy was being reinterpreted.** The task-or-project rule
of ADR-010 was measured on files whose relationships all *inherit* the
project's lag policy, and the plan applied it to an explicit canonical
`LagCalendar.SUCCESSOR` as well — which the enum defines as the successor's
calendar and a Primavera file would mean that way. The rule now applies to
inherited policy only; an explicit `SUCCESSOR` takes the calendar the successor
is scheduled on. Project calendar 08:00–16:00, successor's resource
10:00–18:00, predecessor finishing 09:00 with an hour of lag: inherited starts
the successor at 10:00 and is labelled, explicit at 11:00 and is not.

**A measuring calendar with no working time measured every float as zero.** A
task scheduled on a working resource calendar whose task-or-project measuring
calendar compiles to nothing passed both passes and came out with zero total
float, zero free float and `critical`. The plan now excludes the row as
`ACTIVITY_MEASURE_CALENDAR_EMPTY`, and `Network.validate` refuses a directly
built activity whose `float_calendar` is empty
(`SCHEDULE_MEASURE_CALENDAR_EMPTY`).

**The backward pass did not carry its policy.** The first pass's fix made the
backward pass read the policy off the forward pass, but `BackwardPass` did not
keep it, so a backward pass computed from a retained-logic forward pass could
be handed to `float_analysis` beside an override forward pass over the same
network: both fingerprints matched, the float walked an edge override had
released, and reported minus one hundred of free float. `BackwardPass` now
carries `progress_policy`, the backward fingerprint hashes it (profile
`sto-backward-pass-v4`), and the float refuses the mixed pair by name.

**An assumption survived the exclusion of its row.** The multi-resource union
was appended to `Plan.assumed` inside the calendar resolution, before the
row's constraint was checked; a dateless SNET then excluded the row and the
assumption stayed, counting against a calculation the row took no part in. The
assumption is now returned pending and recorded only after the row is
scheduled, and the plan refuses outright to carry an activity assumption that
names an unscheduled row.

**A bound below the calendar floor was reported as a driver.** With the
project start no longer a base for tasks with predecessors, a lead that
reaches back below the successor calendar's first working moment produced a
bound the calendar overrode — the task was placed at the floor exactly as it
would be with no edge — yet the edge was credited as its driver. A side whose
bound falls below the floor now takes the floor and no driver.

**Evidence wording.** The comprehensive review also found three statements
that exceeded their evidence. This entry said BOILER's lags were all zero; six
are non-zero, all elapsed leads, and the sentence above now says so. ADR-010's
"before" counts for KILN and CALCINER (36 and 260) were not what `main` gives
under the test horizon — the review measured 29 and 130 and that was
reproduced — so the table is corrected and says which revision and horizon
"before" is. And "inherited" meant a row with a mismatching predecessor, which
is triage, not a replayed causal claim; the ADR, the tests and `ACTIVE.md` now
say that. KILN's and CALCINER's late-date and float counts are pinned in
`tests/test_backward_pass_boiler.py` beside BOILER's, the day-5 candidate's
row in `fixtures/README.md` says what it is and is not an oracle for, and the
four tests on Project's own recalculation no longer skip when the unrelated
candidate is absent.
