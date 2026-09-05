# 2026-09-05 — The status date, and which files are allowed to answer

S5. Actual dates, remaining durations, the status date and the out-of-sequence
policies, over the two passes S3 and S4 built. The semantics came out of the
corpus almost without argument; the interesting work was finding out which of
the estate's files are entitled to settle which question, and discovering that
the one the roadmap calls the progress oracle is not entitled to settle the
question it was reached for. What was learned:

## The candidate is an oracle for actuals and not for slack

`BOILER-WG110-day5-candidate.mspdi.xml` is the file the roadmap names as the
only progress oracle. It has eight tasks with actuals — seven complete, one
under way — and reproducing its stored dates was the point of the slice.

It does reproduce them: every activity carrying an actual date comes out on the
dates Project stored, which is trivially true because an actual date is a fact
the pass places unchanged, and is asserted anyway so that a regression would be
visible next to the forward pass's known disagreement about everything else.

But its **late** dates are stale. Each completed row carries a late start about
three weeks after its actual start and a stored `TotalSlack` of 432,000 seconds,
where the same rows in the files Project itself recalculated carry a late start
equal to the actual start and a slack of zero. The candidate was written by
tooling and never recalculated by Project, so its slack describes a plan that no
longer exists.

Reading criticality off it would have produced a rule that agreed with it and
with nothing else. `boiler-after-native-progress.xml` — three tasks completed
natively — and `boiler-roundtrip-project-saved-task43.xml` — one — are the files
that were genuinely recalculated, and they are the ones the two progress rules
are measured against. Four rows in total, which is few, but they are unanimous
and they are the only genuine evidence in the estate.

`tests/test_progress_boiler.py` asserts the candidate's staleness explicitly,
rather than merely not using it, so nobody quotes it later for the question it
cannot answer.

## The completion rule was hiding behind a zero

Those four rows say: late start equals actual start, late finish equals actual
finish, `TotalSlack` zero, `Critical` **false**.

Zero slack is at the threshold those files declare, so S4's rule —
`total_float <= threshold` — calls all four critical, and is wrong on all four.
The correction is two rules, not one, and it would have been easy to ship only
the second:

1. the backward pass **pins** a completed activity to its actual dates, which is
   where the zero comes from; and
2. criticality **excludes** completed activities, which is where the false comes
   from.

The candidate hides both. Its completed rows have large positive slack, so they
are non-critical for an entirely different reason, and a rule fitted to it would
have passed every test the estate could then run.

## Placing the wrong length is not merely wrong, it refuses

The forward pass places an in-progress activity's *remaining* duration. The
backward pass, unchanged, still placed the whole duration — and on SEM-STA-043,
where an activity has eight units of duration and three remaining, there was no
room to fit eight units before the late finish the forward pass had just
implied. `SCHEDULE_FLOOR_EXCEEDED`: the pass refused a schedule it had itself
computed a forward answer for.

The mirror had to go all the way. Both passes now place `activity.remaining`,
which makes `late_start` the latest the *unfinished* work may begin — the mirror
of `remaining_start` — rather than the latest an activity could have started,
which is a question about the past and has no answer.

That changed float too. Measuring a remaining span's late start against an
actual start that predates it reports the delay as slack, so float for an
in-progress activity is measured from its remaining start. Both sides of the
subtraction now describe the same piece of work.

## A claim measured, and withdrawn before it was written down

The first draft of `sto.core.engine.progress` justified reading actual dates
rather than percent-complete fields by asserting that the corpus and the real
files carry rows where the two disagree.

They do not. A probe had read a `value_permille` attribute that does not exist,
`getattr` returned the default, and the file appeared to carry no percentages at
all. It carries them for exactly the rows with actual dates: eight on the
candidate, three on the natively recalculated file, and **no row on either file
disagrees** about having started or finished.

The decision survived on better grounds — a percentage says how much, not when,
and the corpus declares no percentages, so reading one would put the engine
outside its own oracle — but the reason written down was false, and it was two
lines from being committed as evidence. This is the third time in this estate a
confident cause has not survived contact with the data, which is why `AGENTS.md`
says a diagnosis is a claim. The agreement is now asserted in a test, so a file
where the two diverge is a failure to be decided deliberately rather than
resolved by whichever field the code happens to read.

## Nothing here can test the status date

Every BOILER variant in the estate — the untouched source, the before snapshot,
the day-5 candidate, both round-trip files and the natively progressed one —
declares `StatusDate` 2025-05-09T17:00, and every one of them starts on
2026-09-13. The status date is sixteen months before the project start, from the
same 2024-25 template the calendars came from, which S2 found the same way.

So the status date falls outside the compiled window on every real file here.
The plan reports that on `Plan.status_time_outside_window` and carries no status
time, rather than clamping it to the window or scheduling every unfinished
activity from a date sixteen months in the past. The rule that remaining work is
scheduled from the status date is therefore proven by the conformance corpus and
by no file in this estate.

That is asserted as a test rather than left as a note: a file that one day
carries a usable status date will fail it and ask for the claim to be widened.

## The corpus settles the policies, and one refusal

Seven of the eight status cases are declared and all seven pass exactly. Two of
them *are* the decision: SEM-STA-043 and SEM-STA-044 are the same schedule, the
same actuals and the same status time under retained logic and progress
override, and they differ by two units of project finish. A harness that ran
both under one policy would pass one and fail the other, so the policy is read
from the case.

SEM-STA-046 is the case that stops the status date becoming a floor under
everything. It is an unstarted activity with no predecessors in a schedule whose
status time is five, and the corpus gives it a start-no-earlier-than constraint
*at* five to make it start there. If the floor were implicit that constraint
would be redundant and the case pointless.

SEM-STA-045 is the eighth: the `actual_dates` policy over the SEM-STA-043
schedule, carrying `reference_status: native_validation_only` and no forecast at
all. It is refused with `PROGRESS_POLICY_NOT_EVIDENCED` rather than answered.
The refusal is narrowed to schedules that actually carry progress, because the
policy is a project-level setting a planner may have flipped years ago on a
schedule nobody has progressed — refusing those would stop a file importing over
a setting with nothing to act on.

## The corpus is now fully run, so the gate half is asked directly

With the status cases the engine runs every case the corpus declares an answer
for and does not hold back for levelling. `P1-G1` asks for that count *and* for
byte-identity across three processes, so both halves are now asserted:
`tests/test_conformance_determinism.py` checks that the case ids the suite runs
are exactly the corpus's own executable subset — so a case added to the corpus
and quietly not run is a failure — and computes one SHA-256 over every case's
forward, backward and float fingerprints in three subprocesses under three
different `PYTHONHASHSEED` values.

The forward pass's fingerprint profile moved to `sto-forward-pass-v2` at the
same time. It now carries the remaining start, so a progressed schedule's answer
cannot hash the same as the unprogressed one it was computed from.
