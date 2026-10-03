"""S7's pure execution-domain operation; transport and publication are PL4.

Commands name an immutable canonical base hash. Actual history may be added,
never replaced here; a separately audited correction path is intentionally
absent. Percentages and communication are not scheduling inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sto.core.engine import backward_pass, build_plan, float_analysis, forward_pass, roll_up
from sto.core.engine.backward import BackwardPass
from sto.core.engine.forward import ForwardPass
from sto.core.engine.incremental import Recalculation, recalculate_network
from sto.core.engine.plan import Plan
from sto.core.engine.result import SCHEDULED, ScheduleResult, project_result
from sto.core.hashing import canonical_sha256
from sto.core.model.codec import encode_schedule
from sto.core.model.entities import Duration, Schedule
from sto.core.model.enums import ActivityKind, ProgressPolicy


class ExecutionError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True, slots=True)
class ExecutionChange:
    activity_uid: UUID
    expected_hash: str
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    remaining_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class CalculatedState:
    schedule: Schedule
    canonical_hash: str
    horizon: tuple[datetime, datetime]
    plan: Plan
    forward: ForwardPass
    backward: BackwardPass
    result: ScheduleResult
    recalculation: Recalculation | None = None


def _assemble(
    schedule: Schedule,
    canonical_hash: str,
    horizon: tuple[datetime, datetime],
    plan: Plan,
    forward: ForwardPass,
    backward: BackwardPass,
    recalc: Recalculation | None = None,
) -> CalculatedState:
    floats = float_analysis(plan.network, forward, backward, threshold=plan.critical_float_threshold)
    rollup = roll_up(plan.wbs_children, {
        uid: (row.early_start, row.early_finish)
        for uid, row in forward.by_uid().items()
    })
    result = project_result(plan, forward, backward, floats, rollup,
                            canonical_hash=canonical_hash, horizon=horizon)
    return CalculatedState(schedule, canonical_hash, horizon, plan, forward, backward, result, recalc)


def calculate_state(
    schedule: Schedule,
    horizon: tuple[datetime, datetime],
    *,
    epoch: datetime | None = None,
    resource_calendars_apply: bool = True,
) -> CalculatedState:
    """Fresh full recomputation; the reference oracle for S7."""
    canonical_hash = canonical_sha256(encode_schedule(schedule))
    plan = build_plan(schedule, horizon, epoch=epoch,
                      resource_calendars_apply=resource_calendars_apply)
    forward = forward_pass(plan.network, snap_milestones=plan.snap_milestones,
                           progress_policy=plan.progress_policy)
    backward = backward_pass(plan.network, forward)
    return _assemble(schedule, canonical_hash, horizon, plan, forward, backward)


def apply_execution(previous: CalculatedState, change: ExecutionChange) -> CalculatedState:
    """Derive a new immutable canonical document and its calculated result.

    The caller owns authentication, acceptance/audit, optimistic head locking,
    and live_working publication. No database or network side effects occur.
    """
    if change.expected_hash != previous.canonical_hash or previous.canonical_hash != canonical_sha256(encode_schedule(previous.schedule)):
        raise ExecutionError("EXECUTION_STALE_VERSION")
    if not isinstance(change.activity_uid, UUID):
        raise ExecutionError("EXECUTION_ACTIVITY_UNKNOWN")
    by_uid = previous.schedule.activity_by_uid()
    activity = by_uid.get(change.activity_uid)
    if activity is None:
        raise ExecutionError("EXECUTION_ACTIVITY_UNKNOWN")
    prior_result = previous.result.by_uid().get(change.activity_uid)
    if (not activity.active or activity.manual or activity.kind is not ActivityKind.TASK
            or prior_result is None or prior_result.disposition != SCHEDULED):
        raise ExecutionError("EXECUTION_ACTIVITY_UNSUPPORTED")
    if activity.actual_finish is not None:
        raise ExecutionError("EXECUTION_ALREADY_COMPLETE")
    if previous.schedule.project.progress_policy is ProgressPolicy.ACTUAL_DATES:
        raise ExecutionError("PROGRESS_POLICY_NOT_EVIDENCED")
    if activity.remaining_duration is not None and activity.remaining_duration.elapsed:
        raise ExecutionError("EXECUTION_ELAPSED_REMAINING_UNSUPPORTED")
    for value in (change.actual_start, change.actual_finish):
        if value is not None and (
            not isinstance(value, datetime) or value.tzinfo is not None
            or value.microsecond != 0
        ):
            raise ExecutionError("EXECUTION_ACTUAL_TIME_INVALID")
    remaining = change.remaining_seconds
    if remaining is not None and (type(remaining) is not int or remaining < 0):
        raise ExecutionError("EXECUTION_REMAINING_INVALID")
    if change.actual_start is not None and activity.actual_start is not None and change.actual_start != activity.actual_start:
        raise ExecutionError("EXECUTION_ACTUAL_START_IMMUTABLE")
    if change.actual_finish is not None and activity.actual_finish is not None and change.actual_finish != activity.actual_finish:
        raise ExecutionError("EXECUTION_ACTUAL_FINISH_IMMUTABLE")
    start = activity.actual_start or change.actual_start
    finish = activity.actual_finish or change.actual_finish
    if finish is not None and start is None:
        raise ExecutionError("EXECUTION_FINISH_WITHOUT_START")
    if finish is not None and finish < start:
        raise ExecutionError("EXECUTION_ACTUALS_INVERTED")
    if start is None and remaining is not None:
        raise ExecutionError("EXECUTION_REMAINING_REQUIRES_START")
    if start is not None and finish is None and remaining is None and (change.actual_start is not None or activity.remaining_duration is None):
        raise ExecutionError("EXECUTION_REMAINING_REQUIRED")
    if finish is not None:
        if remaining not in (None, 0):
            raise ExecutionError("EXECUTION_FINISHED_REMAINING_NONZERO")
        remaining = 0
    elif start is not None:
        effective = remaining if remaining is not None else activity.remaining_duration.seconds
        if effective == 0:
            raise ExecutionError("EXECUTION_IN_PROGRESS_REMAINING_ZERO")
    if change.actual_start is None and change.actual_finish is None and change.remaining_seconds is None:
        raise ExecutionError("EXECUTION_EMPTY_CHANGE")
    old_duration = activity.remaining_duration or activity.planned_duration
    if remaining is not None and old_duration is not None and old_duration.elapsed:
        raise ExecutionError("EXECUTION_ELAPSED_REMAINING_UNSUPPORTED")
    duration = None if remaining is None else Duration(
        remaining,
        unit=old_duration.unit if old_duration is not None else None,
        source_format_code=old_duration.source_format_code if old_duration is not None else None,
    )
    changed = replace(activity, actual_start=start, actual_finish=finish,
                      remaining_duration=activity.remaining_duration if duration is None else duration)
    if changed == activity:
        raise ExecutionError("EXECUTION_NO_CHANGE")
    schedule = replace(previous.schedule, activities=tuple(
        changed if row.uid == activity.uid else row for row in previous.schedule.activities
    ))
    canonical_hash = canonical_sha256(encode_schedule(schedule))
    plan = build_plan(schedule, previous.horizon, epoch=previous.plan.epoch,
                      resource_calendars_apply=previous.plan.resource_calendars_apply)
    if change.activity_uid not in plan.network.activity_by_uid():
        raise ExecutionError("EXECUTION_ACTIVITY_UNSUPPORTED")
    def context(p: Plan) -> tuple[object, ...]:
        return (
            p.epoch, p.resource_calendars_apply, p.progress_policy,
            p.snap_milestones, p.critical_float_threshold,
            p.status_time_outside_window, p.network.project_start,
            p.network.horizon, p.network.status_time, p.calendars,
            p.wbs_children,
        )
    if context(plan) != context(previous.plan):
        raise ExecutionError("EXECUTION_CONTEXT_CHANGED")
    recalc = recalculate_network(previous.plan.network, plan.network,
                                 previous.forward, previous.backward, activity.uid)
    return _assemble(schedule, canonical_hash, previous.horizon, plan,
                     recalc.forward, recalc.backward, recalc)
