# ADR-006: The schedule store holds documents; result columns wait for the engine

Status: accepted, 2026-09-03

## Context

The design's persistence slice specifies three tables: immutable schedule
versions, a movable head per project and kind, and a per-activity projection
carrying early and late dates, total float, criticality, percent complete and
remaining duration.

The projection is a table of engine output, and the engine does not exist. No
backward pass has been written, criticality has no definition here yet, and the
result types those columns would mirror are not in the model. The float
semantics are due in the backward-pass slice and the criticality threshold is
one of the things the file oracle is expected to settle by fitting it against a
real schedule. Building the columns first means choosing units, nullability and
a criticality rule now and discovering in a later slice which of them were wrong
— in a table that by then has versions pointing at it.

The persistence gate does not ask for it: two schedules importing into two
projects and surviving a restart with identical hashes needs versions, heads and
the stored document, nothing more.

## Decision

The persistence slice ships schedule versions, schedule heads and the stored
canonical document. The per-activity projection lands with the backward pass and
float, when its columns have defined meanings and a result type to mirror.

Queues and tables that would have read the projection read the document until
then. If that proves too slow before the engine arrives, the projection is added
early with a migration — which is the cheap direction, and the reverse is not.

## Consequences

One migration later rather than one wrong table now. Any query wanting float or
criticality is blocked until the pass that computes them exists, which is
accurate: those values have no source before it.

The immutable-version envelope is fixed early and deliberately, because it holds
opaque documents and hashes and does not depend on engine semantics.
