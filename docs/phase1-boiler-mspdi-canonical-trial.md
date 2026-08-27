# Phase 1 — Boiler MSPDI Canonical Import and Deterministic Comparison

Status: **active research phase — structural importer implemented; post-merge hardening active; deterministic scheduling comparison pending**

Related issues: #3 and #5

## Purpose

Use a real Microsoft Project XML/MSPDI shutdown schedule as the first bounded compatibility case for the STO Scheduler + Tracker research repository.

This phase tests whether a vendor-neutral STO canonical model and an adapted deterministic scheduling core can faithfully represent and recalculate a real shutdown schedule without inheriting Microsoft Project as the internal data model.

## Source handling

The real Boiler XML is external test material and is **not committed** to this public repository.

Only manually reviewed, non-sensitive structural metadata, mappings, public synthetic fixtures and sanitized comparison evidence may be committed.

## Verified source inventory

The importer v0.1 external trial recorded:

- MSPDI namespace: `http://schemas.microsoft.com/project`
- 555 tasks
- 95 summary tasks
- 460 leaf activities
- 60 milestones: 58 activity milestones and 2 summary tasks carrying the source milestone flag
- 600 predecessor links, all source type `1` / FS
- 32 resources
- 472 assignments
- 45 calendars
- 8 project-level extended-attribute definitions
- 14 baseline records across task/resource/assignment owners
- schedule-from-start enabled
- project-level minutes/day = 600
- project-level minutes/week = 2400
- task data includes early/late dates, total/free slack, baselines, actual/remaining values, timephased data, custom fields, resources and assignments

These facts define source complexity and deterministic import structure only. They are not evidence of Microsoft Project scheduling-semantic compatibility.

## Delivered structural importer

PR #4 merged importer profile `mspdi-import-v0.1`, providing:

- strict MSPDI root/namespace validation;
- canonical schedule schema v0.1;
- project, WBS, activity, relationship, calendar, resource, assignment, baseline and custom-field mapping;
- typed Project external references;
- normalized structured `VendorExtension` retention for selected unmodelled elements;
- deterministic JSON and SHA-256;
- structural validation;
- sanitized inventory output;
- external-source run tooling;
- public synthetic regression tests.

The external source imported twice under v0.1 with identical canonical hash:

```text
d86a925d387671de79cb094675e233d5b989de226001830f810b89cb37fd7b8b
```

The v0.1 structural validator reported zero errors and zero warnings. The source XML and full source-derived canonical output were not committed.

## Post-merge review and hardening

PR #4 was merged after Codex review usage was exhausted. A direct review of `main` found that the repository contained the structural importer and its importer tests, but not the comparison eligibility profile or deterministic reference engine described in an earlier progress report.

Issue #5 therefore hardens only the structural importer before calculation work proceeds. Importer profile v0.1.1 adds:

- retained summary milestone state;
- fail-closed unknown assignment-resource handling;
- fail-closed outline hierarchy parsing and independent hierarchy validation;
- explicit document-local identity scope;
- explicit durable cross-snapshot identity deferral;
- corrected structured-retention wording, without a lossless XML claim;
- schema/importer top-level contract checks in CI;
- regression coverage for the findings.

The v0.1 canonical hash above remains historical evidence. Because v0.1.1 intentionally changes canonical output, its external Boiler hash must be recorded by a separately labelled rerun after the hardening code is reviewed.

## Canonical model boundary

The minimum canonical entities for this experiment remain:

- `ShutdownEvent` / project scheduling context
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

Imported summary tasks become `WbsNode` records. `work_packages` remain empty because an operational work package is a later configured mapping rather than an automatic synonym for every summary task.

Entity references such as `task:542` are document-local in canonical model v0.1 and must be paired with `source.document_key`. Durable cross-snapshot identities remain unimplemented.

## Preservation boundary

`VendorExtension` means normalized structured source information is retained at a declared location. It does not mean byte-for-byte XML preservation, complete round-trip preservation or semantic understanding. The original MSPDI remains the source-preservation authority.

## Compatibility vocabulary

Every imported semantic is classified as one of:

- `Full`
- `Mapped`
- `Read-only`
- `Write-only`
- `Workflow-gated`
- `Lossy`
- `Preserved-only`
- `Unsupported`

`Full` is the strongest claim and requires deterministic and, where relevant, native round-trip evidence. Import classifications are not destination-system conformance results.

## Next deterministic comparison profile

After importer hardening and the external v0.1.1 structural rerun, the next bounded increment should:

1. define a versioned fail-closed eligibility profile;
2. resolve effective calendars only for the supported subset;
3. project eligible activities and relationships into a separate deterministic engine input;
4. calculate supported task/milestone spans and relationship effects;
5. compare task start/finish, duration, early/late coordinates and float only where the semantic profile supports them;
6. classify every exclusion and difference;
7. retain zero unexplained differences as the requirement for any semantic declared `Full`.

The external Boiler source currently contains 600 FS links, but the canonical relationship vocabulary retains FS, SS, FF and SF for later bounded tests.

## Difference classification

Comparison differences must be classified as:

1. canonical import defect;
2. deterministic calculation defect;
3. unsupported semantic;
4. known vendor-semantic difference;
5. source inconsistency;
6. unexplained difference.

A semantic cannot remain `Full` if unexplained differences exist.

## Native Project boundary

Parsing, transforming or generating valid XML is not proof of Microsoft Project compatibility.

A native result may only be recorded after an identified Microsoft Project desktop edition/version/build:

1. opens generated MSPDI;
2. recalculates it;
3. saves or exports resulting evidence; and
4. permits semantic comparison against the source and canonical result.

Until then, Project compatibility remains unproven.

## Exclusions

Phase 1 continues to exclude:

- P6 integration;
- SAP/Oracle/Maximo adapters;
- EAM write-back;
- UI and mobile execution work;
- AI features;
- optimiser work;
- production-readiness claims.

## Exit criteria

Phase 1 is complete only when:

1. canonical schema v0 is documented;
2. deterministic Boiler import exists;
3. semantic classification is explicit;
4. deterministic schedule comparison evidence is reproducible;
5. no unsupported semantic is silently approximated as `Full`;
6. any native Project claim is backed by real native evidence; and
7. unexplained differences are zero for every semantic declared `Full`.

The structural import and classification foundations are implemented and being hardened. Independent schedule comparison, MSPDI export and native Project evidence remain open.
