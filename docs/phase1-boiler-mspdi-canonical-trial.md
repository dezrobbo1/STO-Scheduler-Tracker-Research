# Phase 1 — Boiler MSPDI Canonical Import and Deterministic Comparison

Status: **active research phase — importer hardening merged; bounded forward-pass comparison implemented; backward/float and native Project evidence pending**

Related issues: #3, #5 and #8

## Purpose

Use a real Microsoft Project XML/MSPDI shutdown schedule as the first bounded compatibility case for the STO Scheduler + Tracker research repository.

This phase tests whether a vendor-neutral STO canonical model and an adapted deterministic scheduling core can faithfully represent and recalculate a real shutdown schedule without inheriting Microsoft Project as the internal data model.

## Source handling

The real Boiler XML is external test material and is **not committed** to this public repository.

Only manually reviewed, non-sensitive structural metadata, mappings, public synthetic fixtures and sanitized comparison evidence may be committed. The full canonical document also remains external because it contains source-derived task, resource and custom-field values.

## Verified source inventory

The external Boiler trial records:

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

## Structural importer history

PR #4 merged importer profile `mspdi-import-v0.1`, providing the first canonical structural import. The external source imported twice under v0.1 with identical canonical hash:

```text
d86a925d387671de79cb094675e233d5b989de226001830f810b89cb37fd7b8b
```

PR #7 then merged the bounded post-merge hardening:

- canonical schema `0.1.1` and importer profile `mspdi-import-v0.1.1`;
- retained summary milestone state;
- fail-closed assignment-resource resolution;
- fail-closed outline hierarchy parsing and independent hierarchy validation;
- explicit document-local identity scope;
- explicit durable cross-snapshot identity deferral;
- corrected structured-retention wording without a lossless XML claim;
- separate preservation of the historical schema `0.1.0` contract;
- regression coverage for the review findings.

The historical v0.1 evidence remains tied to schema `0.1.0` and importer profile `mspdi-import-v0.1`.

## External importer v0.1.1 result

The same external source imported twice under the hardened profile with identical canonical hash.

| Measure | Result |
|---|---:|
| Source SHA-256 | `e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420` |
| Canonical schema | `0.1.1` |
| Importer profile | `mspdi-import-v0.1.1` |
| Canonical SHA-256 | `e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6` |
| Structural validation errors | 0 |
| Structural validation warnings | 0 |
| Repeated import hashes equal | Yes |

This supersedes no historical evidence; it is a separately versioned hardened-import result.

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

Entity references such as `task:542` are document-local in canonical model v0.1.1 and must be paired with `source.document_key`. Durable cross-snapshot identities remain unimplemented.

## Preservation boundary

`VendorExtension` means normalized structured source information is retained at a declared location. It does not mean byte-for-byte XML preservation, complete round-trip preservation or semantic understanding. The original MSPDI remains the source-preservation authority.

## Compatibility vocabulary

Every semantic is classified using the established vocabulary:

- `Full`
- `Mapped`
- `Read-only`
- `Write-only`
- `Workflow-gated`
- `Lossy`
- `Preserved-only`
- `Unsupported`

`Full` is the strongest claim and requires deterministic and, where relevant, native round-trip evidence. Import or calculation-profile classifications are not destination-system conformance results.

## Implemented calculation eligibility profile

Issue #8 introduces:

```text
mspdi-calculation-eligibility-v0.1
```

The profile is deliberately fail-closed. It admits only a bounded subset with:

- schedule-from-start direction;
- active, automatically scheduled, non-null leaf activities;
- parsed non-estimated durations using source duration-format code `5`;
- not-started actual/progress state;
- ASAP constraints without constraint dates or deadlines;
- FS relationships with zero lag only;
- recursively resolved weekly calendars;
- date-specific calendar rules only when wholly outside the project horizon;
- one effective resource-calendar pattern, or identical patterns across assignments;
- explicit task/resource calendar intersection rules;
- consistent assignment work and units;
- predecessor closure so no admitted activity relies on an excluded predecessor.

The full profile and reason-code contract are documented in:

```text
docs/phase1-calculation-eligibility-profile-v0.1.md
```

## Engine-neutral projection and forward pass

Only eligible semantics enter the projection:

- project start;
- activity ID and source order;
- duration seconds;
- milestone flag;
- ASAP constraint;
- effective-calendar reference;
- FS zero-lag relationships.

Task names, notes, source early/late values, slack and Project critical flags are excluded from calculation inputs.

The reference forward pass uses stable topological ordering and calendar-aware working-time arithmetic. It produces engine-native start/finish dates only. It does not yet calculate late dates, float or a Project-labelled critical path.

## External Boiler calculation result

| Measure | Result |
|---|---:|
| Leaf activities considered | 460 |
| Eligible activities | 226 |
| Eligible non-milestones | 202 |
| Eligible milestones | 24 |
| Excluded activities | 234 |
| Eligible relationships | 253 |
| Effective calendar patterns | 5 |
| Source Start/Finish comparisons | 226 |
| Exact coordinate matches | 226 |
| Coordinate differences | 0 |

Reason counts can overlap because one activity may fail several local checks and may also inherit an excluded predecessor.

| Reason code | Activities |
|---|---:|
| `INELIGIBLE_PREDECESSOR` | 219 |
| `MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED` | 12 |
| `WORK_UNITS_INCONSISTENT` | 10 |
| `ACTIVITY_INACTIVE` | 9 |
| `RELATIONSHIP_LAG_UNSUPPORTED` | 6 |
| `DURATION_FORMAT_UNSUPPORTED` | 2 |

The committed sanitized evidence is:

```text
results/phase1/boiler-mspdi-import-and-calculation-evidence-v0.1.1.json
```

## Interpretation of the zero-difference result

The zero-difference result applies only to the frozen 226-activity subset and only to imported source `Start` and `Finish` observations.

It demonstrates that the declared duration, calendar and zero-lag FS semantics are sufficient for the independent reference forward pass to reproduce those source coordinates for that subset.

It does **not** establish:

- Microsoft Project desktop recalculation equivalence;
- early/late date equivalence;
- total/free float equivalence;
- critical-path equivalence;
- correctness for excluded activities;
- MSPDI export or round-trip compatibility;
- production scheduling correctness.

## Difference classification

Future comparisons must classify every difference as:

1. canonical import defect;
2. deterministic calculation defect;
3. unsupported semantic;
4. known vendor-semantic difference;
5. source inconsistency;
6. unexplained difference.

A semantic cannot be declared `Full` while unexplained differences remain.

## Native Project boundary

Parsing, transforming or calculating from XML is not proof of Microsoft Project compatibility.

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
- resource levelling;
- production-readiness claims.

## Next bounded increment

The next calculation slice should remain separate and should:

1. freeze the current eligible subset and profile version;
2. add a deterministic backward pass;
3. define engine-native late dates and float terminology;
4. compare imported source early/late/slack observations without labelling them Microsoft Project-equivalent;
5. classify every difference;
6. retain zero unexplained differences as the requirement for any semantic later declared `Full`.

MSPDI export and native Project evidence remain later, separately reviewed experiments.

## Exit criteria

Phase 1 is complete only when:

1. canonical schema v0 is documented;
2. deterministic Boiler import exists;
3. semantic classification is explicit;
4. deterministic schedule comparison evidence is reproducible;
5. no unsupported semantic is silently approximated as `Full`;
6. any native Project claim is backed by real native evidence; and
7. unexplained differences are zero for every semantic declared `Full`.

The structural import, hardened identity/preservation boundary and bounded forward-pass comparison are now implemented. Backward-pass/float comparison, MSPDI export and native Project evidence remain open.
