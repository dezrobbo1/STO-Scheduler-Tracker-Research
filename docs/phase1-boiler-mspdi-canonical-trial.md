# Phase 1 — Boiler MSPDI Canonical Import and Deterministic Comparison

Status: **active research phase**

Related issue: #3

## Purpose

Use a real Microsoft Project XML/MSPDI shutdown schedule as the first bounded compatibility case for the STO Scheduler + Tracker research repository.

This phase tests whether a vendor-neutral STO canonical model and an adapted deterministic scheduling core can faithfully represent and recalculate a real shutdown schedule without inheriting Microsoft Project as the internal data model.

## Source handling

The real Boiler XML is external test material and is **not committed** to this public repository.

Only non-sensitive structural metadata, mappings, derived fixtures and comparison evidence may be committed.

## Verified source inventory

A local structural inspection of the source XML established:

- MSPDI namespace: `http://schemas.microsoft.com/project`
- 555 tasks
- 95 summary tasks
- 60 milestones
- 600 predecessor links
- 32 resources
- 472 assignments
- 45 calendars
- 8 project-level extended-attribute definitions
- schedule-from-start enabled
- project-level minutes/day = 600
- project-level minutes/week = 2400
- task data includes early/late dates, total/free slack, baselines, actual/remaining values, timephased data, custom fields, resources and assignments

These facts define source complexity only. They are not evidence of compatibility.

## Research boundary

Phase 1 includes:

1. source semantic inventory;
2. canonical STO model v0;
3. MSPDI import mapping;
4. compatibility classification;
5. deterministic comparison for a declared supported profile;
6. export design sufficient to support a later native Project round-trip;
7. native Project evidence only if an identified Microsoft Project desktop build is actually used.

Phase 1 excludes:

- P6 integration;
- SAP/Oracle/Maximo adapters;
- EAM write-back;
- UI work;
- mobile execution UI;
- AI features;
- optimiser work;
- production-readiness claims.

## Canonical model v0 target

The minimum canonical entities for this experiment are:

- `ShutdownEvent`
- `WbsNode`
- `WorkPackage`
- `Activity`
- `Relationship`
- `Calendar`
- `Resource`
- `Assignment`
- `Baseline`
- `ScheduleVersion`
- `ExternalReference`
- `VendorExtension`

The broader product model may later add `ExecutionEvent`, `Blocker`, `Action`, `EvidenceRef` and `MappingProfile`. Their absence from the first import experiment does not imply they are outside the product concept.

## Canonical-vs-vendor rule

A field belongs in the canonical model only when it represents a scheduling/execution concept the STO platform needs to reason about independently of a vendor.

A field belongs in `VendorExtension` when it must survive an import/export round trip but the STO platform does not yet claim semantic understanding.

No unsupported source semantic may be silently discarded or approximated while being labelled fully compatible.

## Compatibility status vocabulary

Every imported semantic must be classified as one of:

- `Full`
- `Mapped`
- `Read-only`
- `Write-only`
- `Workflow-gated`
- `Lossy`
- `Preserved-only`
- `Unsupported`

`Full` is the strongest claim and requires deterministic and, where relevant, native round-trip evidence.

## First deterministic comparison profile

The first comparison should prioritise semantics already represented in the PM-Software research core and present in the Boiler schedule:

- task/milestone spans;
- WBS identity and hierarchy;
- FS/SS/FF/SF relationships;
- positive and negative lag where supported;
- productive working calendars;
- declared supported date constraints;
- task start/finish;
- duration;
- early/late coordinates where supported;
- total/free float where supported;
- completed and in-progress state where the inherited semantic profile is valid.

Anything outside the supported profile must fail closed or be marked preserved-only/unsupported.

## Comparison evidence

Do not reduce the experiment to project finish equality.

Per-activity comparison evidence should include, where supported:

- stable activity identity;
- hierarchy identity;
- start;
- finish;
- duration;
- milestone state;
- relationship type and lag;
- calendar identity;
- constraint type/value;
- early start/finish;
- late start/finish;
- total slack/float;
- free slack/float;
- actual/remaining state.

Differences must be classified as:

1. canonical import defect;
2. deterministic calculation defect;
3. unsupported semantic;
4. known vendor-semantic difference;
5. source inconsistency;
6. unexplained difference.

A semantic cannot remain `Full` if unexplained differences exist.

## Native Project boundary

Parsing, transforming or generating valid XML is not proof of Microsoft Project compatibility.

A native round-trip result may only be recorded after an identified Microsoft Project desktop edition/version/build:

1. opens the generated MSPDI;
2. recalculates it;
3. saves or exports the resulting schedule evidence; and
4. permits semantic comparison against the source/canonical result.

Until then, Project compatibility remains unproven.

## PM-Software inheritance rule

The Phase 0 inheritance audit remains authoritative for reuse decisions.

Useful PM-Software concepts may be selectively reused or adapted, but its frozen research protocols remain in the original repository and are not silently rewritten here.

The existing PM-Software CPM kernel must not be relabelled a production scheduler.

## Exit criteria

Phase 1 is complete only when:

1. canonical schema v0 is documented;
2. deterministic Boiler import exists;
3. semantic classification is explicit;
4. deterministic comparison evidence is reproducible;
5. no unsupported semantic is silently approximated as `Full`;
6. any native Project claim is backed by real native evidence; and
7. unexplained differences are zero for every semantic declared `Full`.
