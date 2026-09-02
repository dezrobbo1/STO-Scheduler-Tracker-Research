# ADR-002: One canonical model with durable cross-snapshot identity

Status: accepted, 2026-09-02

## Context

The research importer produced an untyped dictionary shaped by MSPDI: lags in
tenths of a minute, Microsoft's integer task `Type`, calculated values mixed in
beside inputs as `*_source` keys, and identifiers that were document-local
(`task:322`). It recorded `durable_cross_snapshot_identity: "not_implemented"`.

That model cannot receive a Primavera schedule (no first-class WBS, no activity
codes, no second constraint, no lag calendar) or a CMMS work order, and
re-importing a schedule made every row a new object.

## Decision

A single typed canonical model, `sto-canonical-1.0`, in `src/sto/core/model/`.

- Identity is a UUIDv5 minted from `(schedule_id, source_system, entity_kind,
  external_uid)`, so it is a pure function of the source. Reconciliation on
  re-import tries the external UID, then the GUID, then a configured business
  key, before minting. A row that disappears is reported, never deleted.
- WBS is first class; Microsoft summary tasks are a projection of it, retained
  so they can be written back.
- Values a source file already calculated (early and late dates, float,
  criticality) live in `SourceObservations` and are never scheduling inputs.
  They exist for the file oracle.
- Quantities are integers: durations in seconds, percentages and units in
  per-mille. The hashing boundary refuses floats.
- Times are naive wall-clock. The site's IANA zone is recorded on the schedule
  and never applied to values.
- Entities are frozen `dataclass(slots=True)` with a reflective codec. The core
  stays standard-library only; validation libraries belong at the API edge.

## Consequences

Two imports of one file hash identically, so a hash difference means a real
difference. A later snapshot keeps the identifiers of every row whose UID
survived — verified at 447 activities across the two BOILER snapshots.

Assignments are the exception: Microsoft Project renumbers assignment UIDs, so
they reconcile poorly on their own UID and need a `(task UID, resource UID)`
business key. The mechanism exists; wiring it up is open work.

Refusing floats means every adapter must convert at its boundary rather than
storing what the file happened to contain.
