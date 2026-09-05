# ADR-009: Progress is read from dates, and completion ends criticality

Status: accepted, 2026-09-05

## Context

Both passes now schedule a plan. Neither had any notion of work that had already
happened, and a shutdown schedule is progressed daily — so the engine could
answer questions about a plan and none about the plan being executed.

Reported progress arrives as three facts per activity — an actual start, an
actual finish and a remaining duration — and one per project, the status date,
which Microsoft Project spells `StatusDate` and Primavera calls the data date.
Turning those into a schedule needs four answers, and each has more than one
defensible reading.

**What decides that an activity has started?** The dates say one thing and the
percent-complete fields say another, and they are separate fields that a file
can disagree with itself about.

**Does the status date hold unstarted work back?** Primavera schedules remaining
work from the data date, and it is tempting to read that as a floor under every
unfinished activity. If it is a floor, an unstarted activity with no
predecessors starts at the status date; if it is not, it starts where its logic
puts it.

**What happens to work that started out of sequence** — an activity reporting an
actual start while a predecessor is still unfinished? Retained logic says its
remaining work still waits for the predecessor; progress override says it
carries on. The canonical model already carries both, plus `actual_dates`, and
nothing chose between them.

**Is a completed activity critical?** S4 established `total float <= threshold`
and recorded that the rule does not hold on a progressed file, without
establishing what does.

The first three are questions about declared semantics, so they were asked of
the pinned conformance corpus. The fourth is a question about what Microsoft
Project does, so it was asked of the files Project itself recalculated.

## Decision

**Progress state is read from the actual dates alone.** An actual finish means
complete, an actual start alone means in progress, neither means not started.
Percent-complete fields are not read: a percentage says how much of the work is
done and not *when* any of it happened, and a pass places spans. The corpus
carries no percentage at all, so reading one would put the engine outside the
oracle that bounds it.

**A complete activity is its two actual dates, in both directions.** Its early
dates are its actuals, its late dates are its actuals, and neither its duration,
its calendar, its constraints nor its predecessors recompute them. Its remaining
duration is zero whatever the file wrote, because a finish date and a non-zero
remaining duration are two claims about one thing and the date is the one that
happened.

**An in-progress activity keeps its actual start, and its remaining duration is
placed as a fresh span.** Both passes place the remaining duration, so
`remaining_start` is where the unfinished work begins and `late_start` is the
latest it could begin; the end of the forward span is the forecast finish, and
successors read that. Float for such an activity is measured from its remaining
start, because the actual start cannot move and slack that cannot be taken is
not slack.

**The status date does not floor unstarted work.** It raises the bound only for
work already under way. A schedule that declares no status date gets no floor at
all rather than an invented one.

**The out-of-sequence policy is the project's**: `retained_logic` and `none`
keep the predecessor's forecast finish over the remaining work; and
`progress_override` replaces it with the status date, for activities that have
started. `actual_dates` is **refused** with `PROGRESS_POLICY_NOT_EVIDENCED`
rather than answered — but only on a schedule that actually carries progress, so
a file that merely declares the setting still imports and still schedules.

**An activity that is complete is not critical, whatever its float.** Criticality
becomes `total_float <= threshold and not complete`, and the row records which
of the two reasons applies so that "no slack but already done" never reads as
"has slack".

## Evidence

**The corpus settles the semantics.** All seven of its declared status cases now
pass exactly, and two of them are the decision: SEM-STA-043 and SEM-STA-044 are
the same schedule, the same actuals and the same status time under the two
policies, and they differ by two units of project finish. SEM-STA-046 settles
the floor: it is an unstarted activity with no predecessors in a schedule whose
status time is five, and the corpus gives it a start-no-earlier-than constraint
*at* five to make it start there — which would be redundant if the status date
floored it. SEM-STA-045 is the actual-dates policy over the SEM-STA-043
schedule, and the corpus declares no forecast for it at all; that is why the
policy is refused rather than answered.

**The natively recalculated files settle criticality.** In the two files
Microsoft Project itself recalculated after progress was entered —
boiler-after-native-progress.xml and boiler-roundtrip-project-saved-task43.xml,
both recorded in `fixtures/README.md` and both, like every real schedule, living
outside this repository — every completed activity
carries a late start and late finish equal to its actual dates, a stored
`TotalSlack` of zero, and `Critical` false. Zero slack is at the threshold those
files declare, so the S4 rule alone calls all four of them critical and is wrong
on all four. Both halves of the decision above come from those same four rows:
the pinning and the exclusion.

**The day-5 candidate is not evidence for either.** Its completed rows carry
early dates equal to their actuals — so it is an oracle for those, and the pass
reproduces all eight of its reported rows exactly — but late dates three weeks
later with a positive stored slack, because it was written by tooling rather
than recalculated by Project. Every one of its completed rows is already
non-critical on slack alone, so it cannot distinguish the two rules, and
`tests/test_progress_boiler.py` asserts that it does not so that it is never
quoted for the one it does not test.

## Consequences

The engine now runs every executable case in the conformance corpus. The
`P1-G1` count is reached and its byte-identity half is asserted directly, by
computing one digest over every case's three pass fingerprints in three
subprocesses under three different hash seeds.

The forward pass's fingerprint profile becomes `sto-forward-pass-v2`: it carries
the remaining start, so a progressed schedule's answer cannot hash the same as
the unprogressed one it was computed from.

Two questions are left open rather than answered, and both are recorded in
`docs/goals/ACTIVE.md`:

- **No file here can test the status date.** Every BOILER variant declares
  `StatusDate` 2025-05-09, sixteen months before its own project start — the
  same 2024-25 template the calendars came from. The status date therefore falls
  outside the compiled window on all of them, the plan reports that rather than
  using it, and the rule is proven by the corpus alone. A test asserts this so
  that a file which one day carries a usable status date fails and asks for the
  claim to be widened.
- **No file here carries a Project-recalculated late date for an in-progress
  activity**, so the rule for those is the mirror of the forward pass and is not
  claimed to be Project's.

Whether Primavera's data date is an implicit floor under unstarted work is a
third open question, and it stays open until `DEP-P6-FILE` is met: no Primavera
file exists anywhere in this estate to measure.
