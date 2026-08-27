# Phase 1 calculation eligibility profile v0.1

Status: **bounded research implementation and external Boiler evidence complete on the active draft branch**

Related issue: #8

## Purpose

This increment establishes the first fail-closed boundary between the canonical MSPDI import model and deterministic schedule calculation.

It answers a narrower question than “does the engine match Microsoft Project?”:

> Which imported Boiler activities can be admitted into a deliberately limited, explicitly documented calculation profile without silently approximating unsupported semantics?

The profile is:

```text
mspdi-calculation-eligibility-v0.1
```

It consumes canonical schema `0.1.1` produced by importer profile `mspdi-import-v0.1.1`.

## Claim boundary

The implementation provides:

- deterministic eligibility classification;
- stable exclusion reason codes;
- recursive calendar inheritance resolution for the supported subset;
- a source-independent engine projection;
- an engine-native forward pass;
- source `Start` / `Finish` comparison for eligible activities;
- sanitized reproducible evidence.

It does **not** establish:

- Microsoft Project calculation compatibility;
- Microsoft Project early/late date equivalence;
- total or free float equivalence;
- critical-path equivalence;
- support for non-zero lag;
- SS, FF or SF calculation;
- progress/status-date calculation;
- resource levelling;
- MSPDI export or round-trip compatibility;
- native Microsoft Project evidence;
- production scheduling correctness.

The source `Start` and `Finish` values are imported Project observations. Matching them without executing Microsoft Project desktop is useful deterministic evidence, but it is not a native conformance result.

## Supported activity semantics

An activity is locally eligible only when all applicable checks pass:

- project is scheduled from the start;
- activity is active, non-null and automatically scheduled;
- source task type is `0` for this profile;
- duration is parsed, non-negative and not estimated;
- source duration format is code `5`;
- milestone flag agrees with zero duration;
- source start and finish are present as timezone-naive ISO date/times;
- percent-complete and actual state remain at not-started values;
- remaining duration/work agree with source duration/work;
- no deadline is present;
- constraint type is ASAP (`0`) and no constraint date is supplied;
- task is not effort-driven, recurring, external or a subproject task;
- no non-zero leveling delay is present;
- resource assignments contain no actual/progress state or non-flat contour;
- assigned work and units are consistent with source duration;
- an effective working calendar can be resolved;
- source start plus source duration reproduces source finish under that calendar.

A locally eligible activity can still be excluded after relationship closure.

## Supported relationship semantics

Only these relationships are admitted:

- Finish-to-Start;
- zero lag;
- not cross-project;
- no unmodelled relationship extension.

If a predecessor is ineligible, every dependent successor is also excluded with `INELIGIBLE_PREDECESSOR`. This closure repeats until the eligible network is self-contained.

## Calendar semantics

The profile resolves base-calendar inheritance recursively.

Regular week definitions are normalized into Sunday-to-Saturday working intervals. An interval ending at `00:00:00` is normalized to the end of that day; other cross-midnight intervals fail closed in profile v0.1. A start and finish time of `00:00:00` represents a full 24-hour working day.

Calendar exceptions and special date-specific weekday entries are permitted only when their complete date range is outside the imported project horizon. Any unresolved or overlapping date-specific calendar rule excludes affected activities.

The effective calendar rule is:

1. Explicit task calendar plus `IgnoreResourceCalendar = 1`: use the task calendar.
2. Explicit task calendar plus one effective resource pattern: intersect task and resource working time.
3. No explicit task calendar plus one effective resource pattern: use the resource calendar.
4. No explicit task calendar ind no assigned resource: use the project calendar.
5. Multiple distinct effective resource patterns: exclude unless an explicit task calendar is configured to ignore resource calendars.

Multiple resource-calendar identifiers are permitted only when they resolve to the same weekly pattern.

Zero-duration milestones retain the predecessor finish timestamp without snapping to the next working interval. Non-milestone tasks snap to the next valid working interval.

## Engine-neutral projection

Only eligible facts enter the projection:

- project start;
- activity ID and source order;
- duration seconds;
- milestone flag;
- ASAP constraint;
- effective calendar reference;
- FS zero-lag relationships.

The projection deliberately excludes:

- task names and notes;
- source early/late dates;
- source slack and critical flags;
- unsupported relationships;
- source progress/actuals;
- EAM or operational classifications.

Effective calendars are deduplicated by SHA-256 of the normalized weekly pattern.

## Deterministic forward pass

The reference pass uses a stable topological ordering.

For each non-milestone activity:

1. candidate start is the later of project start and all eligible predecessor finishes;
2. candidate start moves to the next working instant on the effective calendar;
3. duration is added using working-time arithmetic.

For a milestone, calculated start and finish equal the candidate timestamp without working-time snap.

This produces engine-native forward dates only. It does not calculate late dates, float or a Project-labelled critical path.

## External Boiler v0.1.1 evidence

The real Boiler XML remained external and was imported twice. The full canonical document also remained external.

Verified source and import facts:

| Measure | Result |
|---|---:|
| Source SHA-256 | `e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420` |
| Canonical schema | `0.1.1` |
| Importer profile | `mspdi-import-v0.1.1` |
| Canonical SHA-256 | `e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6` |
| Repeated import hashes equal | Yes |
| Tasks | 555 |
| Summary tasks | 95 |
| Leaf activities | 460 |
| Milestones | 60 |
| Relationships | 600 FS |
| Calendars | 45 |
| Resources | 32 |
| Assignments | 472 |
| Baseline records | 14 |

Eligibility and calculation result:

| Measure | Result |
|---|---:|
| Eligible activities | 226 |
| Eligible non-milestones | 202 |
| Eligible milestones | 24 |
| Eligible relationships | 253 |
| Effective calendar patterns | 5 |
| Compared activities | 226 |
| Exact source Start/Finish matches | 226 |
| Coordinate differences | 0 |

The profile, projection and calculation were run twice and produced identical sanitized evidence.

## Exclusion evidence

Reason counts can overlap because one activity may fail several checks and may also inherit an ineligible predecessor.

| Reason code | Activities |
|---|---:|
| `INELIGIBLE_PREDECESSOR` | 219 |
| `MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED` | 12 |
| `WORK_UNITS_INCONSISTENT` | 10 |
| `ACTIVITY_INACTIVE` | 9 |
| `RELATIONSHIP_LAG_UNSUPPORTED` | 6 |
| `DURATION_FORMAT_UNSUPPORTED` | 2 |

Primary exclusion reasons are recorded separately in the committed JSON evidence.

## Evidence hygiene

Committed evidence contains:

- source and canonical hashes;
- structural counts;
- profile and exclusion counts;
- ID-set fingerprints;
- projection/calculation fingerprints;
- coordinate-comparison counts;
- reproducibility flags.

It does not contain:

- the source XML;
- the full canonical model;
- task names;
- notes;
- resource names;
- file-system paths.

Evidence file:

```text
results/phase1/boiler-mspdi-import-and-calculation-evidence-v0.1.1.json
```

## Interpretation

The zero-difference result is meaningful only inside the declared 226-activity subset. It shows that the imported duration, supported calendar and zero-lag FS semantics are sufficient for the reference forward pass to reproduce the source Start/Finish observations for that subset.

It does not justify extending `Full` compatibility to the excluded cohort or to Microsoft Project generally.

The exclusions are useful findings rather than failed tests. They identify the next semantic experiments:

- non-zero lag;
- multiple distinct resource-calendar patterns;
- inconsistent work/units records;
- elapsed-duration formats;
- progress/status-date behavior.

## Next bounded increment

The next calculation increment should remain separate and should:

1. add a deterministic backward pass for the same frozen subset;
2. define engine-native late dates and float terminology;
3. compare source early/late/slack observations without calling them Project-equivalent until evidence supports that label;
4. classify every difference;
5. add native Microsoft Project recalculation evidence only after MSPDI export exists and an identified desktop build is actually used.
