# ADR-004: Cut over before building scheduler depth

Status: accepted, 2026-09-03

## Context

The consolidation design ends with one phase holding five slices: problems and
handover, critical watch, resource levelling, operational constraints, and
cut-over. Cut-over is last, so `Shutdown-Tracker-Claude` stays deployed and
unmaintained until everything before it is finished.

Reading `docs/evidence/PARITY-CHECKLIST.md` against that order shows the
ordering is accidental. Every item on the checklist is delivered by an earlier
phase except three — raising a problem offline, uploading evidence against a
task, and submitting a critical update against a work package — and those three
belong to two slices, problems-and-evidence and critical-watch. Levelling and
operational constraints appear nowhere on it. They are the product's differentiators, not its parity bar, and the frozen
repositories have neither, so deferring them cannot regress anything a user has
today.

The cost of the original order is a stack nobody uses for the length of two
slices that parity does not ask for, while the deployed system carries real
traffic under an agent contract that has been frozen and a schema nobody is
maintaining.

## Decision

Split the final phase. `P5` is cut-over: problems and handover, critical watch,
cut-over itself. `P6` is scheduler depth: resource levelling and operational
constraints, built after the new stack is the live one.

The gate for `P5` is unchanged in substance — the parity checklist driven
through the interface, ports swapped in one redeploy, frozen repositories
archived. The levelling verifier and the determinism cases move to `P6`'s gate,
where the code that has to satisfy them lives.

## Consequences

Cut-over is reached about two slices earlier, and `Shutdown-Tracker-Claude` is
retired sooner, which is the point: a frozen reference that is also production
is the estate's largest standing risk.

Levelling then lands on a system in daily use. That is a benefit for a feature
whose value depends on how planners actually resolve contention, and a cost if
levelling turns out to need a change to the schedule-version envelope — the
envelope is settled by then. `LevellingResult` layering on an unchanged CPM
result, which the design already requires, is what keeps that cost bounded; if
that layering proves impossible, this ordering is what has to be revisited.

Nothing about the deterministic-CPM claim changes. Levelling was already a
separate stage under a pinned solver, outside that claim.
