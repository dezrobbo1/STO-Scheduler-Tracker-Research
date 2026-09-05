"""Float and criticality: arithmetic over the two passes, and no third traversal.

Total float is how long an activity can slip before it moves the project's late
finish; free float is how long it can slip before it moves any successor's early
start. Both are already implied by :mod:`sto.core.engine.forward` and
:mod:`sto.core.engine.backward`, so nothing here walks the network again. What
is decided here is what a float is *measured in*, which of two floats a total
float is, and when a float makes an activity critical -- and all three were
measured against the real schedules rather than chosen.

**A float is working time on the activity's own calendar**, not the difference
between two coordinates -- and "own" means the calendar the *task* carries or
the project's, not the resource's the work was placed on. Microsoft Project
places work on the resource's calendar and measures slack on the task's, which
is why :class:`~sto.core.engine.network.PlannedActivity` carries the two apart:
read off Project's stored dates on the resource calendar the rule below
reproduces the stored ``TotalSlack`` for a quarter of BOILER's activities, and on
the task calendar for all but two (ADR-010). A float is not the difference
between two coordinates. Every other duration in this engine is productive time
on a calendar -- that is what ``PlannedActivity.duration`` means, and what a lag
means -- so a float, which answers "how much longer could this take", has to be
in the same unit or the two cannot be added. The file oracle says the same
thing far more loudly than the argument does: read off Microsoft Project's own
stored early and late dates, the working-time reading reproduces the ``TotalSlack``
Project stored for four hundred of the un-progressed BOILER snapshot's activities
where the coordinate difference reproduces twenty.

**A total float is the smaller of the start float and the finish float.** An
activity's early and late spans can consume a calendar's gaps differently, so
``late_start - early_start`` and ``late_finish - early_finish`` are not the same
number on a schedule with weekends, and neither one alone reproduces what
Project stored. The smaller of the two does: on Project's own dates it gives the
stored ``TotalSlack`` for every activity in KILN and CALCINER, and for all but
two in BOILER. On a continuous calendar the three readings coincide, which is
why the conformance corpus cannot tell them apart and the real files can. Both
components stay on :class:`ActivityFloat` so the pair is inspectable rather than
collapsed.

Float is **signed**. A late constraint can put a late date before an early one,
and that is negative float -- the schedule cannot be delivered as drawn. Taking
an absolute value or clamping at zero would hide exactly the case the number
exists to surface.

Criticality is ``total_float <= threshold`` **and the activity is not already
complete**, where the threshold is the project's own critical-float threshold,
zero unless the source file set one. Both halves are measured. The first
reproduces the ``Critical`` flag Project stored for every activity of the
un-progressed BOILER snapshot **from the file's own slack**, at the threshold
the file declares. The second is what the progressed files add: in the two files
Project itself recalculated after progress was entered, every completed activity
carries a stored total slack of zero -- which is at the threshold -- and a
``Critical`` flag of false. Four activities across the two files, and the
threshold rule alone is wrong on all four. A completed activity cannot be on the
critical path because nothing it does can move the finish date any more.

The two reasons an activity is not critical are kept apart on the row:
``complete`` says which one applies, so "no slack but already done" never looks
like "has slack".

An edge the progress policy released is released here too: the backward pass
reports them on ``overridden_relationships`` and the free float does not read
them, so an activity whose only successor continues from the status date under
``progress_override`` is measured against the project late finish rather than
against work it no longer holds.

What this module does *not* claim is that our own dates reproduce Project's --
they do not, and the forward pass says so in
``docs/history/2026-09-03-forward-pass.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import CompiledIntervals, working_between
from sto.core.hashing import canonical_sha256

from .backward import BackwardPass
from .forward import ForwardPass
from .network import Network, NetworkError, PlannedRelationship, shift_lag

#: Named on the fingerprint so a stored answer says which rule produced it.
#: Version two hashes the two component floats as well as their minimum, so
#: two analyses whose spans straddle the calendar differently do not match.
CRITICALITY_PROFILE = "sto-criticality-v2"


class CriticalityError(NetworkError):
    """A float that cannot be computed, and why, by code.

    Raised for inputs that do not belong together -- a forward and a backward
    pass over different networks -- and for an edge the forward pass could not
    have accepted, which reaching here would mean the passes were run over
    different networks after all.
    """


@dataclass(frozen=True, slots=True)
class ActivityFloat:
    """One activity's slack, in working time on its own calendar.

    ``start_float`` and ``finish_float`` are the two readings the total float is
    the smaller of. They are kept rather than collapsed because when they
    disagree the activity's early and late spans straddle a calendar gap
    differently, which is a fact about the schedule worth being able to see.
    """

    uid: UUID
    total_float: int
    free_float: int
    critical: bool
    start_float: int = 0
    finish_float: int = 0
    #: Reported finished, and therefore not critical whatever the float says.
    #: Kept beside ``critical`` so the two reasons an activity is not critical
    #: -- it has slack, or it is already done -- are told apart on the row
    #: rather than inferred from a float of zero.
    complete: bool = False

    @property
    def negative(self) -> bool:
        """The schedule cannot be delivered as drawn against its late finish."""

        return self.total_float < 0

    @property
    def spans_disagree(self) -> bool:
        """The early and late spans consume the calendar's gaps differently."""

        return self.start_float != self.finish_float


@dataclass(frozen=True, slots=True)
class FloatAnalysis:
    """Float and criticality for every activity, and the rule that produced them."""

    rows: tuple[ActivityFloat, ...]
    threshold: int
    project_late_finish: int
    fingerprint: str = ""

    def by_uid(self) -> dict[UUID, ActivityFloat]:
        return {row.uid: row for row in self.rows}

    def critical_activities(self) -> tuple[UUID, ...]:
        """The critical activities in the forward pass's topological order."""

        return tuple(row.uid for row in self.rows if row.critical)

    def negative_float_activities(self) -> tuple[UUID, ...]:
        return tuple(row.uid for row in self.rows if row.negative)


def signed_working(calendar: CompiledIntervals, start: int, finish: int) -> int:
    """Productive time from ``start`` to ``finish``, negative when it runs backwards.

    :func:`~sto.core.calendar.arithmetic.working_between` answers zero for an
    inverted interval, which is right for measuring work and wrong for measuring
    float: a late date before an early one is a real, reportable deficit.
    """

    if finish >= start:
        return working_between(calendar, start, finish)
    return -working_between(calendar, finish, start)


def span_float(early: int, late: int) -> int:
    """The plain coordinate difference: elapsed slack, not working slack.

    Not what the engine reports, and kept only so the file oracle can show the
    two readings side by side -- it is the one the real schedules rule out.
    """

    return late - early


def _free_float(
    uid: UUID,
    outgoing: tuple[PlannedRelationship, ...],
    early: dict[UUID, tuple[int, int]],
    calendar: CompiledIntervals,
    calendars: dict[UUID, CompiledIntervals],
    project_late_finish: int,
) -> int:
    """Slack against the successors' *early* dates, not the project's late finish.

    An activity with no successors is measured against the project late finish,
    which is what makes an open-ended tail report the same free float as its
    total float rather than an unbounded one.

    Each edge is read the way the forward pass read it: the anchor is this
    activity's finish for FS and FF and its start for SS and SF, the lag is
    consumed on the relationship's own lag calendar, and what the edge bounds is
    the successor's early start for FS and SS and its early finish for FF and
    SF -- the start of its *remaining* work when the successor is under way.
    The remaining gap is measured on **this** activity's calendar, because
    it is this activity that would consume it by slipping. Read off Project's
    own dates that rule reproduces the stored ``FreeSlack`` for about
    ninety-eight in a hundred activities of every real schedule here.
    """

    early_start, early_finish = early[uid]
    if not outgoing:
        return signed_working(calendar, early_finish, project_late_finish)

    slacks: list[int] = []
    for relationship in outgoing:
        anchor = early_finish if relationship.anchors_predecessor_finish else early_start
        lag_calendar = (
            relationship.lag_calendar
            if relationship.lag_calendar is not None
            else calendars[relationship.successor_uid]
        )
        required = shift_lag(lag_calendar, anchor, relationship.lag)
        if required is None:
            # The forward pass already refused this edge; reaching it here would
            # mean the two passes were run over different networks.
            raise CriticalityError(
                "SCHEDULE_LAG_UNREACHABLE",
                relationship.uid,
                f"lag {relationship.lag} from {anchor} leaves the calendar",
            )
        successor_start, successor_finish = early[relationship.successor_uid]
        available = (
            successor_start if relationship.bounds_successor_start else successor_finish
        )
        slacks.append(signed_working(calendar, required, available))
    return min(slacks)


def float_analysis(
    network: Network,
    forward: ForwardPass,
    backward: BackwardPass,
    *,
    threshold: int = 0,
) -> FloatAnalysis:
    """Total float, free float and criticality for every activity in ``network``.

    ``threshold`` is the project's critical-float threshold in seconds: an
    activity is critical when its total float is at or below it. Zero -- the
    default, and what every schedule in this estate declares -- is the ordinary
    "critical means no slack" rule.
    """

    network_fingerprint = network.fingerprint()
    if (
        forward.network_fingerprint != network_fingerprint
        or backward.network_fingerprint != network_fingerprint
    ):
        raise CriticalityError(
            "SCHEDULE_PASS_MISMATCH",
            None,
            "a pass was computed over a different network",
        )
    early = forward.by_uid()
    late = backward.by_uid()

    calendars = {activity.uid: activity.float_calendar for activity in network.activities}
    released = frozenset(backward.overridden_relationships)
    outgoing = {
        uid: tuple(edge for edge in edges if edge.uid not in released)
        for uid, edges in network.successors().items()
    }
    # What an edge into work already under way bounds is the *remaining* span,
    # so that is the start a predecessor's free float is measured against --
    # not the actual start, which happened and which no predecessor can move.
    early_spans = {
        uid: (
            row.early_start if row.remaining_start is None else row.remaining_start,
            row.early_finish,
        )
        for uid, row in early.items()
    }

    complete = forward.complete_activities()

    rows: list[ActivityFloat] = []
    for uid in forward.order:
        calendar = calendars[uid]
        # For work already under way the movable thing is the remaining span,
        # not the actual start -- which cannot move at all, having happened. The
        # backward pass places the same remaining duration, so both sides of
        # this subtraction describe the same piece of work; measuring the late
        # start of the remaining work against an actual start that predates it
        # would report the delay as slack.
        early_start = early[uid].remaining_start
        if early_start is None:
            early_start = early[uid].early_start
        start_float = signed_working(calendar, early_start, late[uid].late_start)
        finish_float = signed_working(
            calendar, early[uid].early_finish, late[uid].late_finish
        )
        total = min(start_float, finish_float)
        free = _free_float(
            uid,
            outgoing[uid],
            early_spans,
            calendar,
            calendars,
            backward.project_late_finish,
        )
        rows.append(
            ActivityFloat(
                uid=uid,
                total_float=total,
                free_float=free,
                critical=total <= threshold and uid not in complete,
                start_float=start_float,
                finish_float=finish_float,
                complete=uid in complete,
            )
        )

    return FloatAnalysis(
        rows=tuple(rows),
        threshold=threshold,
        project_late_finish=backward.project_late_finish,
        fingerprint=_fingerprint(tuple(rows), threshold, backward.project_late_finish),
    )


def _fingerprint(
    rows: tuple[ActivityFloat, ...], threshold: int, project_late_finish: int
) -> str:
    """A hash of the answer, so two runs are compared without comparing objects."""

    return canonical_sha256(
        {
            "profile": CRITICALITY_PROFILE,
            "threshold": threshold,
            "project_late_finish": project_late_finish,
            "rows": sorted(
                [
                    str(row.uid),
                    row.total_float,
                    row.free_float,
                    row.critical,
                    row.start_float,
                    row.finish_float,
                ]
                for row in rows
            ),
        }
    )
