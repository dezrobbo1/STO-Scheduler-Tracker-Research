"""The status date and reported progress: what an actual date does to the pass.

Three facts arrive from the source on every activity -- an actual start, an
actual finish, and a remaining duration -- and one arrives from the project: the
status date, which Microsoft Project spells ``StatusDate`` and Primavera calls
the data date. This module turns those facts into the one question the forward
pass has to ask about each activity: **where may its remaining work begin?**

An activity is in exactly one of three states, and the state is read from the
dates alone rather than from a percentage:

``COMPLETE``
    An actual finish is reported. Its span is its two actual dates and nothing
    recomputes them -- not the duration, not the calendar, not its
    predecessors. SEM-STA-039 is the case that pins this: the activity's
    declared duration is four, its actuals span five, and five is the answer.

    Percent-complete fields are deliberately not read. A percentage says how
    much of the work is done; it does not say *when* any of it happened, and a
    pass places spans. The conformance corpus carries no percentage at all --
    its status cases are actual dates and a remaining duration -- so reading one
    would put the engine outside the oracle that bounds it. On the real files
    the two agree exactly: on the day-5 candidate and on the natively
    recalculated snapshot, the rows with a non-zero duration percentage are
    precisely the rows with actual dates, and no row disagrees about having
    started or finished. So nothing is lost by reading the dates, and the
    agreement is asserted in ``tests/test_progress_boiler.py`` so that a file
    where they diverge is a failure rather than a silent choice of one.

``IN_PROGRESS``
    An actual start with no actual finish. The start is a fact and stays put;
    the remaining duration is placed as a fresh span from the bound below, and
    the end of that span is the activity's forecast finish. Successors read the
    forecast finish, which is what makes SEM-STA-041 place its successor at
    seven rather than at the original planned finish.

``NOT_STARTED``
    Neither date. Scheduled exactly as it was before this slice, on its
    remaining duration -- which defaults to its whole duration when the source
    said nothing.

**The status date does not push unstarted work forward.** It would be easy to
floor every unstarted activity at the status date, and it is wrong: SEM-STA-046
is an activity with no predecessors in a schedule whose status time is five, and
the corpus gives it a start-no-earlier-than constraint *at* five to make it
start there. If the floor were implicit the constraint would be redundant and
the case pointless. Microsoft Project agrees -- rescheduling uncompleted work to
the status date is a command a planner runs, not a property of a recalculation.
Whether Primavera's data date behaves as an implicit floor is **not settled
here**: no Primavera file exists anywhere in this estate to measure
(``DEP-P6-FILE``), so the question is recorded in ``docs/goals/ACTIVE.md``
rather than answered by assumption.

The policy is what happens when work has started **out of sequence** -- an
activity reporting an actual start while a predecessor is still unfinished:

``retained_logic`` and ``none``
    The remaining work still waits for the predecessor's forecast finish. The
    logic is retained; only the completed part escaped it. SEM-STA-043.

``progress_override``
    The remaining work of an activity that has already started continues from
    the status date and its unfinished predecessor logic does not hold it back.
    SEM-STA-044, the same schedule as 043, which finishes two units earlier.

``actual_dates``
    **Refused, not guessed.** SEM-STA-045 is that policy over exactly the 043
    schedule, and the corpus declares no forecast for it: it carries
    ``reference_status: native_validation_only``, which is the corpus saying
    that only a native run can answer it. Producing a number here would be
    inventing an oracle, so this raises ``PROGRESS_POLICY_NOT_EVIDENCED``.

Only an activity that has started is subject to the policy at all. A
not-started activity obeys its logic under every policy, so ``progress_override``
is not a licence to ignore precedence generally -- it is a rule about work
already under way, and that is the bound of what these two cases prove.
"""

from __future__ import annotations

from enum import StrEnum

from sto.core.model.enums import ProgressPolicy

from .network import NetworkError, PlannedActivity

#: Named on the fingerprint so a stored answer says which rules produced it.
PROGRESS_PROFILE = "sto-progress-v1"


class ProgressError(NetworkError):
    """Progress that cannot be scheduled, and why, by code.

    Separate from the two pass errors because it is not the network that is
    wrong: the schedule is well formed and the *rule* for it is not evidenced.
    """


class ProgressState(StrEnum):
    """Which of the three states an activity's actual dates put it in."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


#: The policies that keep precedence over an activity's remaining work.
RETAINING_POLICIES = frozenset({ProgressPolicy.NONE, ProgressPolicy.RETAINED_LOGIC})


def state_of(activity: PlannedActivity) -> ProgressState:
    """The activity's progress state, from its actual dates alone."""

    if activity.is_complete:
        return ProgressState.COMPLETE
    if activity.has_started:
        return ProgressState.IN_PROGRESS
    return ProgressState.NOT_STARTED


def require_supported(policy: ProgressPolicy, progressed: bool) -> None:
    """Refuse a policy this engine has no oracle for, and only when it can bite.

    ``actual_dates`` is refused on a schedule that actually carries progress. On
    a schedule with no actual dates at all the policy has nothing to act on, so
    a file that merely *declares* it still imports and still schedules -- which
    matters because the setting is a project-level field a planner may have
    flipped years ago on a schedule nobody has progressed yet.
    """

    if policy is ProgressPolicy.ACTUAL_DATES and progressed:
        raise ProgressError(
            "PROGRESS_POLICY_NOT_EVIDENCED",
            None,
            "actual_dates has no declared reference forecast (SEM-STA-045); "
            "only a native run can answer it",
        )


def remaining_bound(
    state: ProgressState,
    policy: ProgressPolicy,
    logic_bound: int,
    status_time: int | None,
) -> int:
    """The earliest coordinate an activity's remaining work may begin at.

    ``logic_bound`` is what the predecessors alone require -- whatever the
    forward pass computed before progress was considered. The status time
    raises it for work already under way, and ``progress_override`` replaces it
    for that same work.

    A schedule with no status time gets no floor: nothing is invented, so an
    in-progress activity's remaining work simply follows its logic. That is the
    honest answer to a file that reports actuals without saying what they are
    reported as at.
    """

    if state is not ProgressState.IN_PROGRESS or status_time is None:
        return logic_bound
    if policy is ProgressPolicy.PROGRESS_OVERRIDE:
        return status_time
    return max(logic_bound, status_time)
