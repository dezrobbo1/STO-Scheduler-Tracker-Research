# Phase 1 MSPDI canonical importer v0.1

## Implemented

- Standard-library XML parser restricted to the Microsoft Project MSPDI namespace.
- Vendor-neutral canonical JSON schema v0.1.
- Project, WBS, activities, relationships, calendars, resources, assignments, baselines and custom-field import.
- Deterministic canonical JSON and SHA-256.
- Structured preservation of unmodelled MSPDI elements.
- Custom structural validator.
- Sanitized inventory output.
- External-source run script that keeps real XML and canonical output outside Git.
- Synthetic fixture and 10 automated tests.

No PM-Software source code was copied in this increment. The implementation follows the merged inheritance-audit decisions while retaining an independent product-specific model.

## External Boiler result

The real external Boiler source was imported twice using the same code and environment.

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

Canonical hash for both runs:

```text
d86a925d387671de79cb094675e233d5b989de226001830f810b89cb37fd7b8b
```

The full canonical output was approximately 12 MB and was not committed because it contains source-derived names and values. The real XML was not committed.

## What this proves

This result proves that the current importer can parse the external Boiler MSPDI source into the declared canonical representation deterministically and satisfy the repository's structural validator.

## What this does not prove

It does not prove:

- the new engine reproduces Project schedule calculations;
- Project will reopen a generated file without recalculation differences;
- imported early/late dates or slack are correct;
- calendar inheritance has been resolved correctly;
- round-trip preservation is complete;
- Microsoft Project compatibility;
- production readiness.

## Next bounded increment

Implement deterministic source-coordinate comparison without MSPDI export:

1. derive effective project/task calendars for the supported subset;
2. transform supported activities and relationships into the inherited/adapted scheduling kernel input;
3. calculate start, finish, early/late coordinates and float for explicitly supported cases;
4. classify every excluded activity/relationship and fail closed;
5. compare calculated results with Project source fields;
6. report zero unexplained differences only within the declared supported subset.

Native Microsoft Project round-trip remains a later, separately evidenced step.
