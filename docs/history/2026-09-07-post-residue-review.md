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

## A third pass, and a defect it caught

The reviewer ran once more on the commit above and raised one finding, which
was real and was a blocker: the multi-resource assumption had been added to
every return of `effective_calendar` except the branch for an activity naming
a calendar the file does not carry, so that branch returned four values where
the caller unpacks five. One broken calendar reference raised `ValueError` and
aborted the plan for the whole schedule instead of excluding one row.

Nothing in the suite reached it. No schedule in the estate carries a broken
calendar reference, and the migration turns an unresolved source reference
into "no calendar" before the plan can see one — which is the comprehensive
review's F01, and is why the regression test sets the broken reference on the
canonical row rather than in the XML. The distinction between an unresolved
calendar and an absent one is the reason that branch exists at all, and until
C1 connects the importer to it, the plan's half of it is what can be tested.

## A fourth pass, after the merge

Two findings arrived ten minutes after PR #34 merged, so they are answered
here on the next branch, as `AGENTS.md` provides for.

**A finish-only successor took its start from the compiled window.** When the
project start stopped being a floor for tasks with predecessors, an unstarted
task whose predecessors are all FF or SF was left with no bound on its start at
all, and the missing side fell back to the calendar's first working moment.
That moment is not a schedule input — it is wherever the caller compiled from —
so widening the horizon moved the task earlier while nothing about the schedule
changed. Reproduced: a two-hundred-unit FF successor of a task at project start
100 was placed at 0, 40 or 80 as the window opened at 0, 40 or 80.

The start side now falls back to the **project start**, which is where
Microsoft Project puts an ASAP task nothing else places. The finish side still
falls back to the calendar: an unbounded finish is already implied by the start
bound plus the duration, and flooring it at the project start drags a
lead-placed task back to it — the fifty-six BOILER rows ADR-010 measured, and
the first attempt at this fix did exactly that, taking BOILER from 384 exact to
328 before the asymmetry was understood.

No file in the estate exercises the defect. KILN has fifty-eight finish-only
rows and CALCINER fifty-three, and every one carries a finish bound late enough
that its duration, not the floor, places it; measured across three horizons on
both files, not one row moves. So the agreement counts are unchanged — 384 of
BOILER's 451, 247 of KILN's 416, 1,645 of CALCINER's 1,763 — and the regression
is synthetic, in `tests/test_post_residue_review.py`.

**A count of tests in prose.** `docs/goals/ACTIVE.md` claimed a particular
number of tests per finding. The guard added with the resequencing only caught
digits, so it now catches a number spelled out as well, in every form up to
ninety-nine — the first attempt stopped at twelve, which left the same class
open one word further along.

The first attempt also *rewrote* the counted sentences in the sections of this
entry above, which is the one thing the record is not for: audit is
append-only, and the estate corrects by superseding, never by rewriting. Those
sentences are restored to what they said on 2026-09-07, and this paragraph
supersedes them: what they call twelve tests, one test per finding and four
native-recalculation tests are counts of a suite that has changed since, and
the command in `docs/goals/ACTIVE.md` is what says how many there are now. The
guard is scoped to the documents that describe the repository *now* —
`docs/goals/ACTIVE.md`, `AGENTS.md`, `README.md` — for exactly that reason,
which is the same line the slice-count guard already drew and which the first
attempt crossed.

### What that fix got wrong, and its own review said so

Two things, both fair.

**It superseded an accepted decision without saying so.** ADR-010 measured
that the project start bounds only a task with no predecessors; the fix
applied it to a task that has them, on no oracle, and the test asserted the
resulting date as if it were known. The fallback stays, because the
alternative — a date that moves with the compiled window — is worse and is not
a schedule at all, and because it is the same rule every root already uses.
But it is now written as an amendment to ADR-010 that says in as many words
that this half is an assumption, it is listed among the known gaps with the
file that would settle it, and the row itself reports `FROM_PROJECT_START`
with no driving relationship, so a reader of the result sees that nothing in
the schedule put it there.

**It credited an edge that drove nothing.** With the start floor supplying a
real coordinate, `_driver` still returned the finish edge whenever the start
side had no driver of its own. The FF successor was placed at the project
start with or without its edge, and reported the edge. The replay now runs for
that case too: if the span from the start bound already satisfies the finish
bound, the finish edge moved nothing and is not named.

### And what *that* review said, which was more of the same

Five findings, three of them about the answer just given.

**The label was not in the channel a claim reads.** `FROM_PROJECT_START` is
what an ordinary root reports, and a root's placement is measured, so a
consumer could not tell the guess from the rule. The plan now puts every such
row on `Plan.assumed` as `ACTIVITY_START_UNBOUNDED` — the channel ADR-010
already uses for the successor of an inactive task. BOILER has none, KILN
fifty-eight, CALCINER fifty-three, pinned in
`tests/test_forward_pass_boiler.py`.

**The driver replay snapped a milestone it should have left alone.** Enabling
the replay for the no-start-driver case sent zero-duration rows through
`earliest_span`, which always snaps forward, while `_place` under
`snap_milestones=False` leaves a milestone exactly on its bound. With the
project start in a calendar gap that reopens after the finish bound, the
snapped replay landed past the bound and cleared a driver that had really
placed the row: reproduced at coordinate 15, reported as driven by nothing.
The replay now places a milestone the way the pass does.

**Measured counts had been copied into `docs/goals/ACTIVE.md`.** Numbers from
the real schedules belong in an ADR or here, where they are dated and sit with
the run that produced them; the goal document keeps the qualitative gap and
points at ADR-010.

**The widened count guard stopped at twelve**, leaving the very class it was
widened for open one word further along. It now covers every number word up to
ninety-nine, in digits, words and hyphenated compounds.

**And it had been applied by rewriting this record.** Corrected above.

### A fourth round, and the guard finally ends its class

Three findings, and the two about the guard are the same lesson twice.

**The assumption named rows the fallback never reaches.** An in-progress
activity is based on its actual start and a completed one is pinned to its
actual dates in both directions, so neither uses the project-start floor; the
label is now only on untouched work. The counts on the un-progressed files are
unchanged, because they carry no actuals.

**The count guard was still bounded.** Widening it to ninety-nine left "one
thousand tests" passing, exactly as stopping at twelve had left "thirteen
tests" passing — each attempt ending the class one step past wherever the last
one stopped. It now matches a run of number words at any magnitude, with "and"
allowed between them but never at the start, since "the importer and tests"
is a conjunction and not a count.

**And narrowing its scope had dropped real coverage.** Excluding the dated
records is right; excluding the whole documentation tree with them was not,
and left `docs/evidence/` and `docs/product/` free to grow a count. The guard
now reads every maintained document and skips only `docs/adr/`,
`docs/history/` and the frozen consolidation plan, each for a reason written
beside the list.

### A fifth round: the fallback rested on the window after all

Three findings, one of them the root of the whole thread.

**A schedule that declares no start had no anchor, and took the caller's.**
`build_plan` substituted the compiled window's first coordinate for a missing
`ProjectSettings.start`, so the project-start floor — the fix for the window
dependence — *was* the window again for such a schedule, and moving the window
a day moved the successor a day. It reaches every root too, and predates this
change. A schedule with no declared start now raises
`PROJECT_START_MISSING` rather than inventing an anchor: every floor in the
pass is the project start, and there is no honest substitute for one the file
never gave. All three real schedules declare theirs.

**The label still named rows the fallback cannot reach.** A must-start-on or
must-finish-on row is placed on its coordinate whatever the bounds say, so it
is excluded from the assumption alongside started work. That is the second
narrowing of the same label; what it means is now stated once, in the code:
these are the rows whose start rests on the unmeasured rule, not the rows the
rule happened to move.

**And the count guard had another magnitude past its end.** Twelve, then
ninety-nine, then trillion — each attempt ended the class one step past the
last, because a list has an end and English does not. The scale words are now
matched by their form, `-illion` being productive, so quadrillion and
quintillion are caught by the same rule that catches billion, and there is no
next magnitude to find.

### A sixth round, and the label moves to where the fact is

Two findings, and the first ended a thread rather than another instance of it.

**The assumption was being decided in the wrong place.** Three rounds had each
found another row the label named and the fallback never reached: work already
started, a row pinned by a must-start-on constraint, and now a row a
start-no-earlier-than raises past the floor. Every one of those was a real
mistake, and together they say the design was wrong rather than the filter:
the plan can see that no edge bounds a row's start, but not what then placed
the row. The forward pass can, so it reports it —
`ForwardPass.unbounded_starts`, the rows with predecessors that came to rest
on the project start — and the plan's static label is gone. It is exact by
construction, and the constraint and progress cases fall out of it without a
filter to forget.

Measured on the estate with that in hand: **no row rests on the fallback at
all.** Every activity whose predecessors bound only its finish is placed by its
own duration against that bound, on all three files, which is a stronger
statement than the horizon comparison and is now what the real-file test
asserts.

**And the count guard did not know a dozen.** An exact count that names no
digit is still an exact count, so the collective numerals are in it now.

### A seventh round: the label was still reading the wrong thing

Three findings.

**A finish constraint hid the fallback behind it.** The report was conditioned
on the row's reported `source`, and a finish-no-earlier-than that raises a
bound the span already satisfies changes the source to "constraint" without
moving the start. The report is now decided before any constraint is read,
from the provenance of the *start* bound, and cleared only by a constraint
that actually takes the start side over.

Correcting that exposed the opposite error in the same breath, and with it a
claim made here one round ago that was wrong. Conditioning on the start
bound's provenance alone reported a hundred and eleven rows across KILN and
CALCINER, because every activity whose predecessors bound only its finish
takes the fallback as its start bound. What matters is whether the fallback
*changed the answer*, so the row is now placed a second time with the
calendar's own floor in the fallback's place and reported only if the span
moves. On that reading none of those rows is placed by the fallback — the
finish bound and the row's own duration decide — which is what the previous
round claimed on a condition that could not have shown it either way.

**And real-file counts had reached an engine comment.** Measurements from the
hash-recorded schedules belong in an ADR or here; the comment is qualitative
and points at ADR-010.

**The count guard enumerated multipliers.** "A dozen" was caught and "eleven
dozen" was not. The collectives are units the ordinary number grammar counts
now, which is the fourth and last shape this guard has been wrong in.
