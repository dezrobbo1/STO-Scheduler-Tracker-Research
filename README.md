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
| Decisions | `docs/adr/`, with `LEGACY-INDEX.md` mapping the frozen repositories' ADRs |
| The full design | `docs/roadmap/CONSOLIDATION-PLAN.md` |
| Native round-trip evidence | `docs/evidence/` |
| How decisions were reached | `docs/history/` |
| Real schedules: hashes, provenance, recovery | `fixtures/README.md` |

`sto.legacy` is the previous research importer and forward-pass engine, retained
as the oracle the new engine and the MPXJ interchange service are checked
against, and deleted once that cross-check is green.

Experimental research repository for a **small, focused, adaptable and compatible** shutdown / turnaround / outage scheduling and live-execution platform.

This repository is deliberately separate from:

- `dezrobbo1/PM-Software` — deterministic-AI project-management and scheduling research;
- the existing Shutdown Tracker repository — current product direction.

## Relationship with PM-Software

This repository is an **independent parallel experiment**, not a subordinate implementation of PM-Software.

PM-Software is exploring the broader deterministic-AI core idea. This repository is free to continue pursuing STO-specific scheduling, live execution, interoperability and other ideas when they are producing useful capability or evidence.

Neither project should be frozen simply to avoid overlap. Where both projects investigate similar problems, compare what actually works and selectively reuse useful ideas, tests or code. A shared package or repository merge should happen only if working experiments make that clearly beneficial.

## Current milestone

**Prototype 0 — Local schedule workspace**

Prototype 0 is the first usable vertical slice. It runs locally and now provides:

- Microsoft Project XML/MSPDI import through the browser;
- the complete imported task hierarchy, including unsupported tasks;
- a row-aligned task table and simple Gantt;
- side-by-side imported dates and dates from the current bounded scheduler;
- duration editing for an eligible non-summary, non-milestone task;
- scenario recalculation with moved tasks highlighted against their original calculated bars;
- one-click scenario reset; and
- a compact JSON export of the current workspace state, provenance, relationships and scenario hashes.

The canonical import remains immutable. A duration scenario changes a copy of the engine projection and therefore does not overwrite imported source facts.

### Run the workspace

Python 3.12 or newer is required. From the repository root:

```bash
python -m pip install -e .
python -m sto.legacy workspace
```

The workspace binds to the loopback-only address `127.0.0.1:8765` and opens in the default browser. Use `--no-open` to run it without opening a browser, or `--port` to select another local port.

Import a Microsoft Project XML file, select a row labelled **Calculated**, change its duration in hours, and choose **Recalculate schedule**. Unsupported activities and summary tasks remain visible but view-only. The supplied real XML schedules remain external to this public repository.

See `docs/prototype0-local-schedule-workspace.md` for the exact workflow and current calculation boundary.

## Prior research foundation

**Phase 1 — Boiler MSPDI canonical import and deterministic comparison**

Phase 0 completed the scheduling-core inheritance audit. PR #4 merged the first structural Microsoft Project XML/MSPDI importer. PR #7 completed the bounded post-merge hardening of importer profile `mspdi-import-v0.1.1` and canonical schema `0.1.1`. PR #9 merged calculation profile v0.1 and its external Boiler evidence.

Issue #12 and merged PR #13 added only bounded negative elapsed-day FS-lead support in calculation profile v0.2.

Delivered on `main`:

- MSPDI namespace validation and structural inventory;
- canonical schedule schemas `0.1.0` and `0.1.1`, with the historical contract preserved;
- WBS/activity, relationship, calendar, resource, assignment, baseline and custom-field import;
- deterministic structured retention of selected unmodelled MSPDI fields;
- deterministic canonical JSON and SHA-256;
- fail-closed structural validation;
- explicit document-local identity boundaries;
- synthetic regression fixtures and tests;
- sanitized external Boiler v0.1.1 import and calculation evidence;
- fail-closed v0.1 activity and relationship eligibility classification;
- deterministic FS zero-lag forward pass and source-coordinate comparison.

Phase 1.3 delivered by PR #13 on `main`:

- profile `mspdi-calculation-eligibility-v0.2`;
- FS negative lead only where `LagFormat=8` (`pjElapsedDays`) and raw/normalized lag values agree;
- continuous elapsed-time lead before successor working-calendar normalization;
- latest lag-adjusted candidate selection across multiple predecessors;
- fail-closed milestone, unsupported-format and pre-project calendar-exception guards;
- deterministic external Boiler v0.2 evidence for the bounded admitted subset.

Still not delivered:

- backward pass, late dates or float comparison;
- positive lag, non-elapsed lag or SS/FF/SF calculation;
- progress/status-date calculation;
- resource levelling;
- MSPDI export;
- JSON workspace re-import or durable persistence;
- native Microsoft Project round-trip evidence;
- a production scheduling engine.

See:

- `docs/phase1-boiler-mspdi-canonical-trial.md`
- `docs/phase1-calculation-eligibility-profile-v0.1.md`
- `docs/phase1-negative-fs-lag-v0.2.md`
- `docs/canonical-model-v0.1.md`
- `docs/phase1-import-implementation-v0.1.md`
- issues #3, #5, #8 and #12.

## Commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m sto.legacy workspace
PYTHONPATH=src python -m sto.legacy inventory-mspdi path/to/source.xml
PYTHONPATH=src python -m sto.legacy import-mspdi path/to/source.xml --output .external-results/canonical.json
PYTHONPATH=src python scripts/run_external_calculation_trial.py path/to/source.xml --output .external-results/calculation-evidence.json
PYTHONPATH=src python -m sto.legacy workspace
```

The real source XML and full source-derived canonical output must remain outside this public repository.

## Research direction

The hypothetical product being tested would own only:

- STO scheduling;
- live execution tracking;
- operational forecasting and recovery;
- interoperability between planning systems and EAM/CMMS systems.

Project/P6 and EAM systems are intended to be optional interoperable endpoints rather than hard dependencies. Cost, materials, procurement, inventory and other enterprise functions should remain in the systems that already own them unless a thin read/integration module is justified.

## Claim boundary

Nothing in this repository currently proves:

- Microsoft Project compatibility;
- Primavera P6 compatibility;
- EAM write-back compatibility;
- production scheduling correctness;
- production readiness.

The structural importer and bounded forward-pass experiment provide deterministic research evidence only. Compatibility claims require explicit semantic comparison and native-system conformance testing.
