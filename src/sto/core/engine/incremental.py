"""Conservative component recalculation with the full passes as the oracle.

Only a progress change to one activity on an unchanged graph can take the
bounded path. All graph-connected activities are recalculated in both
directions. A changed project finish (the global late bound), topology, or an
entirely connected network uses the reference full passes instead.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from .backward import BackwardPass, _fingerprint as backward_fingerprint, backward_pass
from .forward import ForwardPass, _fingerprint as forward_fingerprint, forward_pass
from .network import Network
from .progress import relationship_binds, state_of


@dataclass(frozen=True, slots=True)
class Recalculation:
    forward: ForwardPass
    backward: BackwardPass
    mode: Literal["incremental", "full_fallback"]  # diagnostic, outside hashes
    recalculated_activities: int


def recalculate_network(
    previous: Network,
    current: Network,
    previous_forward: ForwardPass,
    previous_backward: BackwardPass,
    changed_uid: UUID,
) -> Recalculation:
    """Recalculate a changed graph; reuse only proven independent components."""

    explicit_late_finish = (
        previous_backward.project_late_finish_explicit
        or previous_backward.project_late_finish != previous_forward.project_finish
    )

    def full() -> Recalculation:
        forward = forward_pass(
            current,
            snap_milestones=previous_forward.snap_milestones,
            progress_policy=previous_forward.progress_policy,
        )
        backward = backward_pass(
            current, forward,
            project_late_finish=(previous_backward.project_late_finish
                                 if explicit_late_finish else None),
        )
        return Recalculation(forward, backward, "full_fallback", len(current.activities))

    if (
        previous_forward.network_fingerprint != previous.fingerprint()
        or previous_backward.network_fingerprint != previous.fingerprint()
        or previous_backward.progress_policy is not previous_forward.progress_policy
        or previous_backward.snap_milestones != previous_forward.snap_milestones
        or explicit_late_finish
        or previous.project_start != current.project_start
        or previous.horizon != current.horizon
        or previous.status_time != current.status_time
        or previous.relationships != current.relationships
        or tuple(row.uid for row in previous.activities)
        != tuple(row.uid for row in current.activities)
        or changed_uid not in current.activity_by_uid()
        or any(a != b for a, b in zip(previous.activities, current.activities) if a.uid != changed_uid)
    ):
        return full()

    adjacent: dict[UUID, set[UUID]] = {row.uid: set() for row in current.activities}
    for edge in current.relationships:
        adjacent[edge.predecessor_uid].add(edge.successor_uid)
        adjacent[edge.successor_uid].add(edge.predecessor_uid)
    component = {changed_uid}
    pending = [changed_uid]
    while pending:
        for neighbour in adjacent[pending.pop()]:
            if neighbour not in component:
                component.add(neighbour)
                pending.append(neighbour)
    if len(component) == len(current.activities):
        return full()

    subset = replace(
        current,
        activities=tuple(row for row in current.activities if row.uid in component),
        relationships=tuple(
            edge for edge in current.relationships
            if edge.predecessor_uid in component and edge.successor_uid in component
        ),
    )
    part_forward = forward_pass(
        subset,
        snap_milestones=previous_forward.snap_milestones,
        progress_policy=previous_forward.progress_policy,
    )
    old_forward = previous_forward.by_uid()
    new_forward = part_forward.by_uid()
    times = tuple(new_forward.get(uid, old_forward[uid]) for uid in previous_forward.order)
    finish = max((row.early_finish for row in times), default=current.project_start)
    if finish != previous_forward.project_finish:
        return full()

    positions = {uid: index for index, uid in enumerate(previous_forward.order)}
    # The pass metadata is assembled in the same traversal order as the full
    # pass, including constraint reports and fallback assumptions.
    def ordered(old, new, key, reverse=False):
        return tuple(sorted(
            (*[row for row in old if key(row) not in component], *new),
            key=lambda row: positions[key(row)], reverse=reverse,
        ))

    fingerprint = current.fingerprint()
    forward = replace(
        previous_forward,
        times=times,
        project_finish=finish,
        deferred_constraints=ordered(previous_forward.deferred_constraints, part_forward.deferred_constraints, lambda row: row.activity_uid),
        constraint_violations=ordered(previous_forward.constraint_violations, part_forward.constraint_violations, lambda row: row.activity_uid),
        unbounded_starts=ordered(previous_forward.unbounded_starts, part_forward.unbounded_starts, lambda uid: uid),
        fingerprint=forward_fingerprint(times, current.project_start, finish, previous_forward.snap_milestones),
        network_fingerprint=fingerprint,
    )
    part_backward = backward_pass(subset, part_forward, project_late_finish=finish)
    old_backward = previous_backward.by_uid()
    new_backward = part_backward.by_uid()
    late_times = tuple(new_backward.get(uid, old_backward[uid]) for uid in previous_forward.order)
    released = tuple(edge.uid for edge in current.relationships if not relationship_binds(
        previous_forward.progress_policy,
        state_of(current.activity_by_uid()[edge.successor_uid]),
        current.status_time,
    ))
    backward = replace(
        previous_backward,
        times=late_times,
        deferred_constraints=ordered(previous_backward.deferred_constraints, part_backward.deferred_constraints, lambda row: row.activity_uid, reverse=True),
        overridden_relationships=released,
        fingerprint=backward_fingerprint(late_times, finish, released, previous_forward.progress_policy, previous_forward.snap_milestones),
        network_fingerprint=fingerprint,
    )
    return Recalculation(forward, backward, "incremental", len(component))
