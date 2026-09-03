# STO Scheduler + Tracker

STO is a shutdown, turnaround and outage scheduler. It imports from a CMMS, from
Primavera P6 or from Microsoft Project; it tracks, manages and schedules
execution in real time; and it exports back to any of them.

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
| Product contracts carried from the frozen repositories | `docs/product/` |
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
