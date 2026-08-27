# STO Scheduler + Tracker Research

Experimental research repository for a **small, focused, adaptable and compatible** shutdown / turnaround / outage scheduling and live-execution platform.

This repository is deliberately separate from:

- `dezrobbo1/PM-Software` — deterministic scheduling-core research source;
- the existing Shutdown Tracker repository — current product direction.

## Current phase

**Phase 1 — Boiler MSPDI canonical import and deterministic comparison**

Phase 0 completed the scheduling-core inheritance audit. Phase 1 now tests a real external Microsoft Project XML/MSPDI shutdown schedule against a new vendor-neutral canonical model.

Implemented in the active draft PR:

- MSPDI namespace validation and structural inventory;
- canonical schedule schema v0.1;
- WBS/activity, relationship, calendar, resource, assignment, baseline and custom-field import;
- structured preservation of unmodelled MSPDI fields;
- deterministic canonical JSON and SHA-256;
- custom structural validation;
- synthetic regression fixture and 10 automated tests;
- sanitized external Boiler import evidence.

See:

- `docs/phase1-boiler-mspdi-canonical-trial.md`
- `docs/canonical-model-v0.1.md`
- `docs/phase1-import-implementation-v0.1.md`
- issue #3 and draft PR #4.

## Commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m sto_scheduler_core inventory-mspdi path/to/source.xml
PYTHONPATH=src python -m sto_scheduler_core import-mspdi path/to/source.xml --output .external-results/canonical.json
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

The current importer proves deterministic structural transformation only. Compatibility claims must come from explicit deterministic comparison and native-system conformance testing.
