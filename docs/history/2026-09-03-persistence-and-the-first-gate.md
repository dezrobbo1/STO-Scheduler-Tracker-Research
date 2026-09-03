# 2026-09-03 — Persistence, and the first gate crossed

PL1 built: the schedule-version envelope in PostgreSQL, the API over it, and
the gate — two schedules, two projects, a restart, identical hashes.

## What was decided on the way

**Not V002 verbatim.** The design said to take Shutdown-Tracker-Claude's V002
migration as written. It types its columns with enums the design elsewhere
forbids, and its `project_snapshots` is the same concept as a `baseline`
schedule version. V001 here carries V002's projects, source files and import
batches with enums replaced by CHECK constraints, and one envelope instead of
a snapshot table plus an envelope. ADR-007.

**The hash is recomputed on every load.** The gate could have been satisfied
by storing a hash and reading it back. That proves nothing about whether the
document survived JSONB. Every load decodes the stored document, re-encodes
it canonically and compares; the API test then does the same from outside.
JSONB keeps integers, strings and structure exactly, which is why there are
no floats in a canonical document in the first place.

**A corrupt version is loud and local.** First written so that one version
failing verification stopped the process booting. That hid which project was
wrong behind a process that would not start. Now the project is reported by
`/api/health`, its routes return an error, and the others are served.

**A differing project GUID is recorded, not refused.** The CLI requires an
explicit override when an identity map's project GUID differs from the
file's. The API does not: importing into a project is the operator's
statement that this file is that shutdown, and the two real BOILER snapshots
declare different project GUIDs. The mismatch is on the import record.

**8092, not 8090.** The design puts the API on 8090 so the Caddyfile does not
change at cut-over. 8090 is the deployed Java API today. The new stack
listens beside it until PL12 swaps them.

## The dependency boundary, in practice

`uv` manages an `api` extra (FastAPI, uvicorn, psycopg, pydantic) and a `test`
extra (the HTTP test client). The bare suite runs with nothing installed and
skips the persistence tests; the `api` CI job installs the extras, runs with
a PostgreSQL service and `STO_REQUIRE_DB=1`, and then applies the migrations
to a fresh database and runs the drift guard. `sto serve` on a bare
interpreter says which extra it needs instead of tracing back.

## The rule that went live

`infra/migrations/` exists, so `PR-migrations` fired as designed: the suite
failed and asked for the enforcing test. `infra/migrations/CHECKSUMS` pins
each file; `tests/test_migrations_are_immutable.py` holds every file to its
pin and the numbering to contiguity; `scripts/db/apply-migrations.sh`,
carried from the frozen repository, refuses a changed file at the database.

## The gate

Six of six. Two criteria rest on the BOILER files and one on a database, and
each says so in the roadmap; the gate was crossed with `STO_REQUIRE_BOILER=1`
and `STO_REQUIRE_DB=1` set, so nothing skipped.
