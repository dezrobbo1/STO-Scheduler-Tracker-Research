"""One row per activity, and what produced it (slice PL3).

ADR-006 deferred this table on the grounds that its columns had no meanings
yet: there was no backward pass, criticality had no definition, and the result
types the columns would mirror were not in the model. S3 to S6 supplied all
three, so this is the type they mirror.

It is an assembly, not a calculation. Every value here comes from a pass, the
float, the rollup or the plan's dispositions; nothing is derived a second time,
because a projection that recomputed anything could disagree with the result
it claims to project.

**What makes a stored row answerable.** A date on its own says nothing about
what produced it -- which horizon, which progress policy, which criticality
threshold, which version of which pass. So a result carries a
:class:`Provenance` naming all of them and hashes it together with the rows.
Two results with the same hash were computed from the same document by the
same rules; two with different hashes say so before anyone compares dates.

The projection is in this package rather than in persistence because it is
engine output, and because a caller who never stores anything still wants one
place that says what an activity's answer is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from sto.core.hashing import canonical_sha256

from .backward import BACKWARD_PASS_PROFILE, BackwardPass
from .criticality import CRITICALITY_PROFILE, FloatAnalysis
from .forward import FORWARD_PASS_PROFILE, ForwardPass
from .plan import Plan
from .progress import PROGRESS_PROFILE, ProgressState
from .rollup import ROLLUP_PROFILE, Rollup

__all__ = [
    "RESULT_PROFILE",
    "ActivityResult",
    "Provenance",
    "RelationshipResult",
    "ScheduleResult",
    "SummaryResult",
    "fingerprint_result",
    "project_result",
]

#: Named on the hash, so a stored result says which assembly produced it.
RESULT_PROFILE = "sto-result-v1"

#: A row the plan scheduled and the passes placed.
SCHEDULED = "scheduled"
#: A row the plan would not schedule, carrying the code that says why.
EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything that decided the numbers, so a stored row can be re-derived.

    The horizon is here because it is the caller's choice and not the file's,
    and a pass over a wider window is a different calculation even from the
    same document. The profiles are here because a rule change bumps one of
    them, and a stored result computed under the old rule should not be
    mistaken for one computed under the new.
    """

    canonical_hash: str
    epoch: datetime
    horizon_start: datetime
    horizon_finish: datetime
    progress_policy: str
    critical_float_threshold: int
    #: The status date the passes actually used, and whether the source carried
    #: one that had to be dropped. A run with no status date and a run whose
    #: status date fell outside the compiled window produce the same dates from
    #: different inputs, so a stored result that could not tell them apart
    #: would present discarded progress context as an absence of it.
    status_time: datetime | None = None
    status_time_outside_window: bool = False
    forward_profile: str = FORWARD_PASS_PROFILE
    backward_profile: str = BACKWARD_PASS_PROFILE
    criticality_profile: str = CRITICALITY_PROFILE
    rollup_profile: str = ROLLUP_PROFILE
    progress_profile: str = PROGRESS_PROFILE
    result_profile: str = RESULT_PROFILE

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_hash": self.canonical_hash,
            "epoch": self.epoch.isoformat(),
            "horizon_start": self.horizon_start.isoformat(),
            "horizon_finish": self.horizon_finish.isoformat(),
            "progress_policy": self.progress_policy,
            "critical_float_threshold": self.critical_float_threshold,
            "status_time": None if self.status_time is None else self.status_time.isoformat(),
            "status_time_outside_window": self.status_time_outside_window,
            "forward_profile": self.forward_profile,
            "backward_profile": self.backward_profile,
            "criticality_profile": self.criticality_profile,
            "rollup_profile": self.rollup_profile,
            "progress_profile": self.progress_profile,
            "result_profile": self.result_profile,
        }


@dataclass(frozen=True, slots=True)
class ActivityResult:
    """One activity's answer, or the reason it does not have one."""

    uid: UUID
    disposition: str
    #: Every field below is ``None`` for an excluded row: it was not placed, so
    #: it has no dates rather than dates that mean nothing.
    early_start: datetime | None = None
    early_finish: datetime | None = None
    late_start: datetime | None = None
    late_finish: datetime | None = None
    #: Where the unfinished part of work under way begins. Set for exactly the
    #: in-progress rows, which is the corpus's own convention.
    remaining_start: datetime | None = None
    total_float: int | None = None
    free_float: int | None = None
    critical: bool | None = None
    state: str | None = None
    #: What put the activity where it is: a predecessor, the project start, a
    #: constraint, its own actual dates, or the status date.
    placed_by: str | None = None
    #: The relationship that drove it, when one did.
    driving_relationship_uid: UUID | None = None
    #: What bounded the late span, which in a chain is a different edge from
    #: what bounded the early one -- a successor rather than a predecessor. A
    #: result that stored four dates and the cause of two of them could not
    #: explain the other two.
    late_placed_by: str | None = None
    late_driving_relationship_uid: UUID | None = None
    #: A hard constraint that overrode precedence, and the coordinate the logic
    #: required instead. The forward pass reports these rather than losing
    #: them, and a stored calculation that dropped the report would present a
    #: schedule whose retained logic is not honoured as an ordinary one.
    constraint_override: str | None = None
    #: The code the plan excluded it under, and the assumptions it rests on.
    exclusion_code: str | None = None
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationshipResult:
    """What the plan did with one edge, when it did anything worth recording.

    An edge is not a row of the result the way an activity is: it has no dates
    of its own. But a dropped edge and an edge kept under a labelled rule both
    decided the dates that *are* stored, and a result that recorded neither
    would present assumption-dependent answers as fully evidenced.
    """

    uid: UUID
    disposition: str
    code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """One summary row's span, rolled up from what sits beneath it."""

    uid: UUID
    start: datetime
    finish: datetime
    #: Placed rows anywhere beneath it, so an empty branch is visibly empty.
    placed: int


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """A whole calculation: every row, every summary, and what produced them."""

    provenance: Provenance
    activities: tuple[ActivityResult, ...]
    summaries: tuple[SummaryResult, ...]
    #: Edges the plan dropped, and edges it kept under a labelled assumption.
    relationships: tuple[RelationshipResult, ...] = ()
    #: Summary rows with nothing placed beneath them, named rather than absent.
    empty_summaries: tuple[UUID, ...] = ()
    fingerprint: str = ""

    def by_uid(self) -> dict[UUID, ActivityResult]:
        return {row.uid: row for row in self.activities}


def project_result(
    plan: Plan,
    forward: ForwardPass,
    backward: BackwardPass,
    floats: FloatAnalysis,
    rollup: Rollup,
    *,
    canonical_hash: str,
    horizon: tuple[datetime, datetime],
) -> ScheduleResult:
    """Assemble one result from the passes that produced it.

    ``canonical_hash`` is the stored document's, so the result names the
    schedule it was computed from rather than being trusted to belong to it.
    """

    provenance = Provenance(
        canonical_hash=canonical_hash,
        epoch=plan.epoch,
        horizon_start=horizon[0],
        horizon_finish=horizon[1],
        progress_policy=plan.progress_policy.value,
        critical_float_threshold=plan.critical_float_threshold,
        status_time=(
            None
            if plan.network.status_time is None
            else plan.to_datetime(plan.network.status_time)
        ),
        status_time_outside_window=plan.status_time_outside_window,
    )

    early = forward.by_uid()
    late = backward.by_uid()
    slack = floats.by_uid()
    assumptions: dict[UUID, list[str]] = {}
    edges: list[RelationshipResult] = []
    for row in plan.assumed:
        if row.kind == "activity":
            assumptions.setdefault(row.uid, []).append(row.code)
        else:
            edges.append(RelationshipResult(row.uid, SCHEDULED, row.code, row.detail))
    for dropped in plan.excluded:
        if dropped.kind != "activity":
            edges.append(RelationshipResult(dropped.uid, EXCLUDED, dropped.code, dropped.detail))

    # Two things the passes report and the plan does not know about. Both
    # describe a placement that rests on something other than measured file
    # evidence, so a stored row that dropped them would look ordinary.
    overrides = {
        violation.activity_uid: (
            f"{violation.type.value}: pinned to {violation.coordinate}, "
            f"logic required {violation.logic_required}"
        )
        for violation in forward.constraint_violations
    }
    unbounded = frozenset(forward.unbounded_starts)

    def row_assumptions(uid: UUID) -> tuple[str, ...]:
        codes = list(assumptions.get(uid, ()))
        if uid in unbounded:
            # The forward pass places these by the project start because no
            # edge bounds their start, and records them because that rule has
            # no supporting evidence in any file here.
            codes.append("ACTIVITY_START_NOT_BOUNDED")
        return tuple(codes)

    rows: list[ActivityResult] = []
    for activity in plan.network.activities:
        uid = activity.uid
        placed = early[uid]
        late_row = late[uid]
        float_row = slack[uid]
        rows.append(
            ActivityResult(
                uid=uid,
                disposition=SCHEDULED,
                early_start=plan.to_datetime(placed.early_start),
                early_finish=plan.to_datetime(placed.early_finish),
                late_start=plan.to_datetime(late_row.late_start),
                late_finish=plan.to_datetime(late_row.late_finish),
                remaining_start=(
                    None
                    if placed.remaining_start is None
                    else plan.to_datetime(placed.remaining_start)
                ),
                total_float=float_row.total_float,
                free_float=float_row.free_float,
                critical=float_row.critical,
                state=placed.state.value,
                placed_by=placed.source,
                driving_relationship_uid=placed.driving_relationship_uid,
                late_placed_by=late_row.source,
                late_driving_relationship_uid=late_row.driving_relationship_uid,
                constraint_override=overrides.get(uid),
                assumptions=tuple(row_assumptions(uid)),
            )
        )

    for excluded in plan.excluded:
        if excluded.kind != "activity":
            continue
        rows.append(
            ActivityResult(
                uid=excluded.uid,
                disposition=EXCLUDED,
                exclusion_code=excluded.code,
                assumptions=tuple(row_assumptions(excluded.uid)),
            )
        )

    summaries = tuple(
        SummaryResult(
            uid=row.uid,
            start=plan.to_datetime(row.start),
            finish=plan.to_datetime(row.finish),
            placed=row.placed,
        )
        for row in rollup.spans
    )

    result = ScheduleResult(
        provenance=provenance,
        activities=tuple(rows),
        summaries=summaries,
        relationships=tuple(edges),
        empty_summaries=rollup.empty,
    )
    return replace(result, fingerprint=fingerprint_result(result))


def fingerprint_result(result: ScheduleResult) -> str:
    """A hash over the rows and what produced them.

    Sorted by identifier rather than by the order the passes happened to
    produce, so two runs that agree hash alike whatever order they walked in.
    """

    def moment(value: datetime | None) -> str | None:
        return None if value is None else value.isoformat()

    return canonical_sha256(
        {
            "provenance": result.provenance.to_dict(),
            "activities": sorted(
                [
                    str(row.uid),
                    row.disposition,
                    moment(row.early_start),
                    moment(row.early_finish),
                    moment(row.late_start),
                    moment(row.late_finish),
                    moment(row.remaining_start),
                    row.total_float,
                    row.free_float,
                    row.critical,
                    row.state,
                    row.placed_by,
                    None if row.driving_relationship_uid is None else str(row.driving_relationship_uid),
                    row.late_placed_by,
                    None
                    if row.late_driving_relationship_uid is None
                    else str(row.late_driving_relationship_uid),
                    row.constraint_override,
                    row.exclusion_code,
                    list(row.assumptions),
                ]
                for row in result.activities
            ),
            "relationships": sorted(
                [str(row.uid), row.disposition, row.code, row.detail]
                for row in result.relationships
            ),
            "summaries": sorted(
                [str(row.uid), moment(row.start), moment(row.finish), row.placed]
                for row in result.summaries
            ),
            "empty_summaries": sorted(str(uid) for uid in result.empty_summaries),
        }
    )
