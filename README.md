# STO Scheduler + Tracker

STO is a shutdown, turnaround and outage scheduler being built to import from
a CMMS, from Primavera P6 or from Microsoft Project; to track, manage and
schedule execution in real time; and to export back to any of them. Today it
imports Microsoft Project XML into a canonical model, stores and calculates an
immutable baseline, and creates one persisted duration scenario that shows
downstream movement behind real user/session/project authorization.
`docs/goals/ACTIVE.md` says what is built and what is next.

This repository is the product monorepo. `dezrobbo1/Shutdown-Tracker-Claude` and
`dezrobbo1/Shutdown-Tracker` are frozen references being folded in here;
`dezrobbo1/PM-Software` continues as independent research and supplies the
semantic conformance suite. See `docs/adr/ADR-001-consolidation-and-repository-topology.md`.

## Canonical model

Every source lands in one typed model, `sto-canonical-1.0`, whose identifiers
are stable across snapshots and source systems:

```bash
PYTHONPATH=src python3 -m sto.cli canonicalise path/to/schedule.xml --quiet
PYTHONPATH=src python3 -m sto.cli reconcile earlier.xml later.xml
```

`reconcile` answers the question a re-import actually raises: which rows carried
their identity forward, which are new, and which the later file no longer has.

## Where things are

| | |
|---|---|
| What is being built now | `docs/goals/ACTIVE.md` |
| Working mode and boundaries | `AGENTS.md` |
| Decisions | `docs/adr/`, with `docs/adr/LEGACY-INDEX.md` mapping the frozen repositories' ADRs |
| The design, frozen 2026-09-02 and not maintained | `docs/roadmap/CONSOLIDATION-PLAN.md` |
| Current and inherited product contracts | `docs/product/` |
| Native round-trip evidence | `docs/evidence/` |
| How decisions were reached | `docs/history/` |
| Real schedules: hashes, provenance, recovery | `fixtures/README.md` |

`sto.legacy` is the previous research importer and forward-pass engine, retained
as the oracle the new engine and the MPXJ interchange service are checked
against, and deleted once that cross-check is green.

## The legacy workspace

`sto.legacy` still ships the Prototype 0 browser workspace it came with: import
an MSPDI schedule, browse the hierarchy, edit one duration and recalculate. It
is retained as a reference, not as the product direction.

```bash
PYTHONPATH=src python3 -m sto.legacy workspace
```

It binds to the loopback interface only and holds one in-memory session; nothing
is persisted.

## The consolidated local planner

Apply every migration and run the FastAPI application against the local STO
PostgreSQL database:

```bash
PGHOST=127.0.0.1 PGPORT=5433 PGUSER=postgres PGDATABASE=sto \
  scripts/db/apply-migrations.sh
export STO_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/sto
export STO_AUTH_MASTER_KEY="$(uv run --extra api python -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
uv run --extra api python -m sto.cli auth bootstrap-admin trial-admin
uv run --extra api python -m sto.cli serve
```

The bootstrap command prompts for the password without putting it in shell
history and shows the TOTP enrolment material once. It does not grant access to
projects that pre-date V005; grant each one deliberately:

```bash
uv run --extra api python -m sto.cli auth grant-project \
  PROJECT_UUID trial-admin admin
```

Keep `STO_AUTH_MASTER_KEY` in the deployment's secret store and stable across
restarts. `STO_SESSION_TTL_SECONDS` defaults to eight hours. Set
`STO_COOKIE_SECURE=1` whenever the browser is served over TLS; the local
loopback HTTP default is `0`.

Open [the local planner](http://127.0.0.1:8092) and sign in. The page creates projects,
imports MSPDI/XML, calculates the baseline and edits the planned duration of
one supported leaf activity. Its JSON download is prototype scenario state; it
is not a Microsoft Project writer. Scenario resets write an authenticated,
append-only V006 event while preserving the immutable scenario and calculation.
Disabling a user is refused while that account is the last enabled
administrator of any project; grant another enabled administrator or reassign
the membership first. There is no silent emergency-disable bypass.
