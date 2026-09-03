# ADR-007: One envelope for every kind of schedule version

Status: accepted, 2026-09-03

## Context

The design took `Shutdown-Tracker-Claude`'s V002 migration verbatim — projects,
source files, import batches, and `project_snapshots` — and added a
schedule-version envelope beside it. Two things stopped that being literal.
V002 types its status columns with PostgreSQL enums from V001, and the design
elsewhere decides TEXT + CHECK, never enums, because an enum rebuild is a
migration of its own. And `project_snapshots` — an immutable imported
schedule with a status — is the same thing as a schedule version of kind
`baseline`; carrying both means two tables, two status machines and a join,
for one concept.

The design also specified a per-activity projection table in the same slice,
which ADR-006 deferred until the engine gives its columns meanings.

## Decision

`infra/migrations/V001__projects_sources_and_schedule_versions.sql` carries `projects`, `source_files` and `import_batches`
from V002 with enums replaced by CHECK constraints, and one envelope:

- `schedule_versions` — immutable rows. Kind (`baseline`, `approved_forecast`,
  `live_working`, `scenario`), a per-project sequence, a parent, the cause
  (`import`, `progress`, `planner_edit`, `review`, `promotion`) and its id, the
  full canonical document, the identity map after this version, and the
  document's canonical hash computed before the row is written.
- `schedule_heads` — `(project, kind) → version`. The only thing that moves.

An accepted import is a `baseline` version caused by its import batch. There
is no `project_snapshots`.

Every version stores its full document. Deltas are the live loop's concern
and arrive with it; a fifty-versions-then-full rule invented before the
first delta exists would be designed against nothing.

The hash is recomputed from the stored document on every load. A version
that does not hash to what it says is not served: its project is reported
by the health endpoint and its routes return an error, and the process
stays up for the projects that are fine.

A later import into a project reconciles against the current baseline's
identity map. The project is the operator's statement that these files are
the same shutdown, so a differing declared project GUID is recorded on the
import rather than refused — the two real BOILER snapshots differ exactly
that way and are the same shutdown.

## Consequences

One concept, one table, one status machine. The persistence gate is a
property of this envelope: import, restart, identical hash — proved by
re-deriving the hash from JSONB, which is the part that could have silently
changed a value and did not.

The resident working model is built from heads at boot and is never the
source of truth. When the engine arrives, its results are a new version of
the appropriate kind with `engine_profile` set; nothing here changes shape.

What is knowingly absent: deltas, the projection table (ADR-006), and any
version kind other than `baseline` being written — the columns exist so
that adding them is a new cause and kind, not a new table.
