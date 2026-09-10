# ADR-013: One immutable duration scenario before live editing

Status: accepted, 2026-09-10

## Context

PL13 made a stored baseline calculation visible, but a planner still could not
change an input and see the engine move the network. Prototype 0 demonstrated
that interaction in memory. Reusing its workspace would create a second
scheduling authority beside the canonical model, version envelope and stored
result introduced since then.

The existing envelope already reserves `scenario` versions and `planner_edit`
causes. It does not yet record what input caused a scenario version, protect a
browser edit from an out-of-date head, or define what reset means.

## Decision

PL14 edits only `planned_duration_seconds` on one active, automatic,
not-started leaf task that the baseline engine calculates without an
assumption. Milestones, progressed tasks, manual or inactive tasks, excluded
rows and assumed rows receive a controlled refusal. Planned and remaining
duration move together where the source supplied both, because a not-started
task's remaining work is its full work. A source that explicitly says a
not-started task has zero remaining duration is not offered for editing and a
direct request receives a controlled refusal; PL14 does not reinterpret that
contradictory progress state.

An edit derives a complete canonical document from the current immutable
baseline and stores it as a new immutable `scenario` version. The baseline
document and its calculation are never updated. V004 adds an append-only
`scenario_changes` row naming the project, source baseline, scenario version,
activity, old seconds and new seconds. Where a not-started source carried a
remaining-duration mirror, the row records its old and synchronised new value
too, so the lineage names every canonical input that changed. A database
trigger verifies that the two versions belong to the project, have the
required kinds and name that change as the scenario's `planner_edit` cause. A
second trigger refuses an
update or deletion of that lineage.

Reset returns success only when the state read after publication still names
the exact baseline version and calculation selected under the project lock.
A concurrent import or calculation produces a stale-state conflict rather
than a false baseline-success message.

The candidate runs through the production plan, passes, float calculation,
result projection and WBS rollup before publication. Under one project lock,
the operation then rechecks the caller's `expected_version_id` and the
baseline version and writes the version, change, calculation and scenario head
in one transaction. A head that moved yields a conflict and stores nothing.

There is one active local scenario per project. A later edit replaces that
head with another immutable single-edit scenario derived from the baseline.
Reset removes only the scenario head, making the baseline calculation active
again; scenario versions, changes and results remain audit history. A new
baseline import also clears the old scenario head because it names a different
source baseline.

The planner API returns baseline and scenario results separately. The page
shows imported, baseline and scenario dates; marks the edited row and every row
whose calculated span changed; and keeps normal, assumed, deferred-constraint
and excluded dispositions visible. Reload and process restart reconstruct the
active state from PostgreSQL. Export is labelled
`sto-prototype-scenario-state-1` and carries version, change, result and
disposition provenance. It is not an MSPDI or `.mpp` export.

## Consequences

The first editable loop uses the consolidated canonical and persistence stack.
It introduces no in-memory scheduling authority and no mutation of imported
data. Expected-version protection is sufficient for local sequential use and
does not claim to be an edit lease or collaboration protocol.

Predecessors, constraints, calendars, resources, progress, task creation,
multi-edit scenarios, promotion and arbitrary undo remain later slices. The
legacy workspace stays reference evidence until this PR is accepted; no PL14
route calls it.
