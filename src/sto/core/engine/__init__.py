"""The scheduling engine: what the calendars and the network are for.

:mod:`sto.core.engine.network` is the input -- integer coordinates and compiled
intervals, carrying no policy. :mod:`sto.core.engine.plan` is where a canonical
schedule becomes one of those, and is where every policy decision lives.
:mod:`sto.core.engine.forward` is the earliest pass over all four relationship
types and :mod:`sto.core.engine.backward` its mirror, the latest.
:mod:`sto.core.engine.criticality` is float and criticality: arithmetic over the
two passes rather than a third traversal.

The status date, progress and the rollup to summary tasks are the next slices
and are deliberately absent rather than stubbed.
"""

from .backward import (
    BACKWARD_PASS_PROFILE,
    FROM_PROJECT_FINISH,
    ActivityLateTimes,
    BackwardPass,
    DeferredLateConstraint,
    backward_pass,
)
from .criticality import (
    CRITICALITY_PROFILE,
    ActivityFloat,
    FloatAnalysis,
    float_analysis,
    signed_working,
    span_float,
)
from .forward import (
    FORWARD_PASS_PROFILE,
    FROM_CONSTRAINT,
    FROM_PROJECT_START,
    FROM_RELATIONSHIP,
    ActivityTimes,
    ConstraintViolation,
    DeferredConstraint,
    ForwardPass,
    forward_pass,
)
from .network import (
    BACKWARD_CONSTRAINTS,
    DEFERRED_CONSTRAINTS,
    FORWARD_CONSTRAINTS,
    BackwardPassError,
    ForwardPassError,
    Network,
    NetworkError,
    PlannedActivity,
    PlannedRelationship,
    shift_lag,
    unshift_lag,
)
from .plan import SCHEDULED_KINDS, Excluded, Plan, build_plan

__all__ = [
    "BACKWARD_CONSTRAINTS",
    "BACKWARD_PASS_PROFILE",
    "CRITICALITY_PROFILE",
    "DEFERRED_CONSTRAINTS",
    "FORWARD_CONSTRAINTS",
    "FORWARD_PASS_PROFILE",
    "FROM_CONSTRAINT",
    "FROM_PROJECT_FINISH",
    "FROM_PROJECT_START",
    "FROM_RELATIONSHIP",
    "SCHEDULED_KINDS",
    "ActivityFloat",
    "ActivityLateTimes",
    "ActivityTimes",
    "BackwardPass",
    "BackwardPassError",
    "ConstraintViolation",
    "DeferredConstraint",
    "DeferredLateConstraint",
    "Excluded",
    "FloatAnalysis",
    "ForwardPass",
    "ForwardPassError",
    "Network",
    "NetworkError",
    "Plan",
    "PlannedActivity",
    "PlannedRelationship",
    "backward_pass",
    "build_plan",
    "float_analysis",
    "forward_pass",
    "shift_lag",
    "signed_working",
    "span_float",
    "unshift_lag",
]
