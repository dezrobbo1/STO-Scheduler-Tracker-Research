# Phase 0 — Scheduling-Core Inheritance Audit

Status: **Draft for review**

Source repository reviewed: `dezrobbo1/PM-Software` (`main`)
Target repository: `dezrobbo1/STO-Scheduler-Tracker-Research`

## Purpose

This phase decides what, if anything, should be inherited from the separate `PM-Software` deterministic scheduling research before any scheduling-core code is copied into this repository.

The target product hypothesis is different from `PM-Software`: this repository is investigating a small, STO-specific scheduling + live-execution kernel with vendor-neutral interoperability. `PM-Software` remains an independent research source and is not modified by this work.

## Source boundary observed

The current PM-Software Phase 1 reference prototype explicitly describes itself as a bounded research instrument rather than a production scheduler, optimiser, project-management application or native-file adapter. It makes no Microsoft Project or Primavera P6 compatibility claim.

Its executable package is divided into:

- `canonical` — loading, ordering, reference validation and frozen-suite handling;
- `calendars` — productive working-time arithmetic and signed lag handling;
- `cpm` — bounded reference scheduling calculations and a separate objective policy used only by preregistered research cases;
- `validation` — independent result validation and evidence checks;
- `execution` — deterministic suite execution and artifact writing;
- `provenance` — canonical JSON, SHA-256 and runtime/evidence identity.

The implemented semantic subset includes FS/SS/FF/SF relationships, positive and negative lag on the successor calendar, selected lower-bound constraints, completed-actual immutability, in-progress remaining work at deterministic status time, retained-logic/progress-override treatment, restricted resource handling and deterministic project finish. Several broader semantics deliberately fail closed.

## Inheritance matrix

| PM-Software source component | Current purpose | Required STO purpose | Classification | Reason | Existing tests | Boundary / risk |
|---|---|---|---|---|---|---|
| `canonical/loader.py` | Validate/load frozen canonical research cases and references | Load STO canonical schedule documents and validate stable identities/references | **adapt** | Validation/order/reference mechanics are useful, but the loader is coupled to frozen-case structure and expected-result research fixtures | Reuse validation ideas; not unchanged | Must not import PM frozen-suite authority into STO product model |
| `canonical/model.py` | Minimal immutable `LoadedCase` wrapper | Rich vendor-neutral STO domain model | **replace** | Current model is a research-case envelope, not a schedule domain model | No | New canonical entities required |
| `canonical/frozen_suite.py` | Discover and pin preregistered frozen fixtures | Regression/conformance corpus management | **wrap** | Useful pattern for pinned fixtures, but STO needs separate real-schedule and adapter-conformance suites | Reuse pattern, not corpus authority | PM fixtures remain frozen in source repo |
| `calendars/arithmetic.py` | Working-interval arithmetic, productive duration and signed lag | Core calendar arithmetic for native STO scheduler | **reuse with narrow adaptation** | This is one of the strongest reusable technical components | Reuse tests wherever semantics remain identical | Must later extend for real Project/P6 calendar semantics, time zones, exceptions and DST |
| `cpm/kernel.py` | Bounded reference scheduling producer | Deterministic STO scheduling engine | **adapt heavily** | Provides valuable deterministic relationship/status mechanics, but is intentionally incomplete and research-profile-specific | Reuse semantic micro-tests as regression tests | No production or Project/P6 compatibility claim may transfer |
| `cpm/objective.py` | Research objective ranking for two preregistered capacity-one cases | Not required for first STO scheduling core | **not relevant initially** | Initial product proof is schedule semantics and interoperability, not optimisation | Keep in PM-Software | Optimisation remains separate research |
| `execution/*` | Run frozen semantic suite and write deterministic artifacts | Headless compatibility/conformance test harness | **wrap** | Execution/evidence discipline is useful, but STO runtime execution events are a different domain concept | Reuse harness patterns | Do not confuse PM “execution harness” with field execution tracking |
| `validation/result_validator.py` | Independent validation path that does not call CPM producer | Independent schedule-result/conformance validator | **reuse concept; adapt implementation** | Independence from producer is a major strength for Project/P6 comparison | Reuse many assertions/patterns | Must gain adapter-specific semantic comparison rules |
| `validation/evidence.py` | Schema/hash/evidence consistency | Compatibility-trial evidence and reproducible comparison records | **adapt** | Strong provenance approach, but current evidence schema is frozen-research-specific | Reuse hash/evidence principles | STO evidence schema must be new and independently versioned |
| `provenance/canonical_json.py` | Deterministic canonical JSON serialization | Stable hashing/version comparison for canonical STO artifacts | **reuse likely** | Vendor-neutral deterministic serialization is directly useful | Reuse tests after dependency review | Verify exact serialization assumptions before copying |
| `provenance/runtime.py` | Runtime/environment identity and evidence projection | Test-run provenance, not production business state | **wrap / research-only** | Useful for conformance experiments; too environment-specific for core product entities | Reuse research tests | Keep separate from business audit trail |
| Frozen semantic fixtures | 50 preregistered semantic micro-tests | Regression seed for deterministic core | **reuse as inherited test corpus, read-only** | Valuable low-level coverage | Yes, unchanged copies only if provenance/licence/history is recorded | They do not prove Project/P6 compatibility |
| Native-validation structure | Record separate pending native requirements | Project/P6 conformance evidence | **reuse concept** | Directly aligned with destination-system verification | Reuse structure principles | Native result must never be fabricated |
| Phase 0/1 governance | Freeze research claims and stop conditions | Research discipline for compatibility trials | **reference, do not inherit as authority** | The discipline is valuable but the new repository has different research questions | No automatic carry-over | PM governance remains authoritative only in PM-Software |

## STO canonical model gap

The current PM model does **not** provide the canonical domain required by this repository. The target model should be defined independently around at least:

- `Shutdown` / event identity;
- `WBSNode`;
- `Activity`;
- `Relationship`;
- `Calendar`;
- `Resource`;
- `Assignment`;
- `WorkPackage`;
- `Baseline`;
- `ScheduleVersion`;
- `ExternalReference`;
- `VendorExtension`;
- `ExecutionEvent`;
- `Blocker`;
- `Action`;
- `EvidenceRef`;
- `MappingProfile`.

The canonical model must not be a Microsoft Project schema, a P6 schema or an EAM schema. Unsupported vendor facts should be preserved through `VendorExtension`/source metadata rather than silently discarded or promoted into core semantics.

## Initial reuse decision

### Reuse first

1. Calendar arithmetic concepts and tests.
2. Deterministic canonical JSON / hashing concepts.
3. Independent validator architecture.
4. Semantic micro-test corpus as a regression seed.
5. Native-validation and evidence discipline.

### Adapt before reuse

1. CPM kernel.
2. Canonical loader.
3. Evidence writer/schema.
4. Execution harness.

### Do not inherit into the initial STO core

1. Objective/optimisation ranking.
2. PM-specific frozen governance as target-repository authority.
3. The current minimal `LoadedCase` model as the STO domain model.

## First technical milestone after this audit

The next bounded experiment should be **Phase 1 — Boiler MSPDI Canonical Import and Deterministic Comparison**.

It should use one real Microsoft Project XML schedule and test only the architectural premise:

1. parse the real MSPDI source without modifying it;
2. populate a new vendor-neutral canonical model;
3. preserve unsupported Project fields as source/vendor metadata;
4. reproduce task hierarchy, IDs, relationships, calendars, resources, assignments and relevant custom fields;
5. calculate only the explicitly supported deterministic subset;
6. compare calculated values with source facts without claiming Project equivalence;
7. export a complete MSPDI candidate;
8. open/recalculate in Microsoft Project only as a separately recorded native validation step;
9. classify every difference as explained, unsupported, lossy or defect.

No UI, EAM connector, cost module, AI feature or optimiser belongs in that milestone.

## Phase 0 exit recommendation

The audit supports reuse, but **not a wholesale copy of PM-Software**. The preferred approach is to create a new STO canonical package and selectively port tested low-level components behind that new model. PM-Software stays intact as the research source and regression reference.
