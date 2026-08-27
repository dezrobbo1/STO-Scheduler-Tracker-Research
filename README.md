# STO Scheduler + Tracker Research

Experimental research repository for a **small, focused, adaptable and compatible** shutdown / turnaround / outage scheduling and live-execution platform.

This repository is deliberately separate from:

- `dezrobbo1/PM-Software` — deterministic scheduling-core research source;
- the existing Shutdown Tracker repository — current product direction.

## Current phase

**Phase 0 — Scheduling-core inheritance audit**

The first task is to decide which PM-Software components should be reused, adapted, wrapped, replaced or left behind before any scheduling code is copied into this repository.

See `docs/research/PHASE-0-INHERITANCE-AUDIT.md` and issue #1.

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

Compatibility claims must come from explicit conformance and native-system testing.
