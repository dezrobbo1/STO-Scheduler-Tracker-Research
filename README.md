# STO Scheduler + Tracker Research

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

Prototype 0 is the first usable vertical slice over the Phase 1 research core:

- run a browser workspace bound to the local computer;
- import a complete Microsoft Project XML/MSPDI schedule;
- inspect its summary hierarchy and leaf activities in one task table;
- compare imported Start/Finish observations with engine-native calculated dates for the currently admitted subset;
- inspect the same rows on a simple imported-versus-calculated Gantt;
- select a calculation-supported, non-milestone activity and change its working duration;
- recalculate the supported network and highlight moved downstream activities;
- reset scenario changes without discarding the import;
- export the current local prototype state as JSON.

The workspace keeps the canonical import immutable. Duration changes are scenario overrides applied only to a copied engine projection. Summary rows and excluded activities retain imported dates but receive no invented calculated dates.

Install the checkout in editable mode, then start the workspace (the same commands work in PowerShell):

```bash
python -m pip install -e .
sto-scheduler-core workspace
```

An MSPDI file can be opened at startup, and automatic browser opening can be disabled:

```bash
sto-scheduler-core workspace path/to/source.xml --no-browser
```

Then open `http://127.0.0.1:8765/`. The server binds only to the loopback interface. The imported schedule and scenario state remain in memory; stopping the process clears them unless JSON was exported.

See `docs/prototype0-local-schedule-workspace.md` for the exact boundary and acceptance flow.

## Phase 1 foundation

**Boiler MSPDI canonical import and deterministic comparison**

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
PYTHONPATH=src python -m sto_scheduler_core inventory-mspdi path/to/source.xml
PYTHONPATH=src python -m sto_scheduler_core import-mspdi path/to/source.xml --output .external-results/canonical.json
PYTHONPATH=src python scripts/run_external_calculation_trial.py path/to/source.xml --output .external-results/calculation-evidence.json
PYTHONPATH=src python -m sto_scheduler_core workspace
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
