# Phase 1 MSPDI canonical importer v0.1

## Current status

PR #4 merged the first structural importer. It was automatically tested but merged after Codex review limits were reached. A direct post-merge review identified bounded hardening work tracked in issue #5 and branch `phase1-importer-post-merge-hardening`.

The merged implementation did **not** contain the comparison eligibility profile or reference scheduling engine described in an earlier progress report. The correct delivered scope is the structural importer documented here.

## Implemented

- Standard-library XML parser restricted to the Microsoft Project MSPDI namespace.
- Vendor-neutral canonical JSON schema v0.1.
- Project, WBS, activities, relationships, calendars, resources, assignments, baselines and custom-field import.
- Deterministic canonical JSON and SHA-256.
- Normalized structured retention of selected unmodelled MSPDI elements.
- Custom structural validator.
- Sanitized inventory output.
- External-source run script that keeps real XML and canonical output outside Git.
- Synthetic fixtures and automated importer/schema-contract tests.

No PM-Software source code was copied. The implementation follows the merged inheritance-audit decisions while retaining an independent product-specific model.

## Post-merge hardening v0.1.1

The review correction adds:

- summary-task milestone state to canonical WBS records;
- fail-closed assignment resource resolution;
- fail-closed outline-level and expected-parent validation;
- independent canonical hierarchy validation;
- explicit document-local identity scope and source-derived document key;
- explicit durable-identity deferral;
- narrowed preservation wording: normalized structured retention, not lossless XML preservation;
- standard-library CI checks that keep the checked-in JSON Schema top-level/source contract aligned with importer output;
- regression tests for every review finding;
- corrected README and Phase 1 status records.

This hardening does not add schedule calculation, MSPDI export or native Project compatibility.

## External Boiler result from importer v0.1

The real external Boiler source was imported twice using the same code and environment before post-merge hardening.

| Measure | Result |
|---|---:|
| Source bytes | 3,734,688 |
| Tasks | 555 |
| Summary tasks | 95 |
| Leaf activities | 460 |
| Milestones | 60 total: 58 activity, 2 summary |
| Relationships | 600 |
| Relationship types | 600 FS |
| Calendars | 45 |
| Resources | 32 |
| Assignments | 472 |
| Custom-field definitions | 8 |
| Baseline records | 14 |
| Structural validation errors | 0 |
| Structural validation warnings | 0 |
| Repeated-import canonical hashes equal | Yes |

Importer v0.1 canonical hash for both runs:

```text
d86a925d387671de79cb094675e233d5b989de226001830f810b89cb37fd7b8b
```

That hash is historical evidence for importer profile `mspdi-import-v0.1`. Hardening v0.1.1 intentionally changes canonical output by adding explicit identity boundaries and summary milestone state, so a separately labelled external rerun is required before recording a v0.1.1 canonical hash.

The full canonical output was not committed because it contains source-derived names and values. The real XML was not committed.

## What this proves

The existing result proves that importer v0.1 parsed the external Boiler MSPDI source into its declared canonical representation deterministically and satisfied the repository's structural validator.

The hardening tests prove the reviewed importer defects are covered on synthetic public fixtures. Until the external Boiler rerun is recorded, they do not replace the historical Boiler evidence above.

## What this does not prove

It does not prove:

- the new engine reproduces Project schedule calculations;
- Project will reopen a generated file without recalculation differences;
- imported early/late dates or slack are correct;
- calendar inheritance has been resolved correctly;
- round-trip preservation is complete;
- durable cross-snapshot identity exists;
- Microsoft Project compatibility;
- production readiness.

## Next bounded increment

After post-merge hardening is reviewed and merged:

1. rerun the external Boiler structural import under importer profile v0.1.1 and commit only reviewed sanitized evidence;
2. define a fail-closed schedule-calculation eligibility profile;
3. derive effective project/task calendars for the supported subset;
4. project supported activities and relationships into a separate deterministic engine input;
5. calculate dates and float for explicitly supported cases;
6. compare calculated results with Project source fields;
7. report zero unexplained differences only within the declared supported subset.

Native Microsoft Project round-trip remains a later, separately evidenced step.
