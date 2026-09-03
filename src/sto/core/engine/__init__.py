"""The scheduling engine: what the calendars and the network are for.

:mod:`sto.core.engine.network` is the input -- integer coordinates and compiled
intervals, carrying no policy. :mod:`sto.core.engine.plan` is where a canonical
schedule becomes one of those, and is where every policy decision lives.
:mod:`sto.core.engine.forward` is the earliest pass over all four relationship
types. The backward pass, float and criticality are the next slice and are
deliberately absent rather than stubbed.
"""

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
    DEFERRED_CONSTRAINTS,
    FORWARD_CONSTRAINTS,
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
)
from .plan import SCHEDULED_KINDS, Excluded, Plan, build_plan

__all__ = [
    "DEFERRED_CONSTRAINTS",
    "FORWARD_CONSTRAINTS",
    "FORWARD_PASS_PROFILE",
    "FROM_CONSTRAINT",
    "FROM_PROJECT_START",
    "FROM_RELATIONSHIP",
    "SCHEDULED_KINDS",
    "ActivityTimes",
    "ConstraintViolation",
    "DeferredConstraint",
    "Excluded",
    "ForwardPass",
    "ForwardPassError",
    "Network",
    "Plan",
    "PlannedActivity",
    "PlannedRelationship",
    "build_plan",
    "forward_pass",
]
