# P1-G2 post-RC02 current-root review — 2026-09-25

Status: **CURRENT ROOTS RECOMPUTED — EXACT RC01 NATIVE INPUT READY; NATIVE RUN REQUIRED**

This append-only review starts from main
`a4a401c42dcacfb3122467b017607aa6be1ee0e5`, after the bounded RC02 production
correction. It changes no production scheduler, importer, canonical model,
persistence, API, UI or gate state.

## Correction to the first PR #62 review

The first version of this review copied `diagnostic_group` and
`dependency_role` from the historical 422-slot diagnosis through the RC02
production verifier. Surviving mismatch keys proved the current inventory, but
did not prove that the old rows were still first divergences or followed the old
driver paths.

This version does not use those labels as classification inputs. It reads the
exact external BOILER baseline, executes the current production importer,
migration, plan builder, forward pass, backward pass and float analysis, and
then repeats the source-coordinate replay against the current result:

1. forward fields use source predecessor coordinates through current production
   bounds, placement and driver selection;
2. late fields use source successor late coordinates through the corresponding
   current backward primitives;
3. float is recalculated from the source early/late coordinates using current
   production float semantics and actual selected candidates;
4. Start and Finish take the newly calculated Early Start/Early Finish
   provenance; and
5. Critical inherits the newly calculated Total Float provenance.

Every dependency path and driver recorded in the companion JSON comes from that
run. Historical labels are comparison-only. The current production projection
and remaining-key-set hashes exactly match the merged RC02 production record.

The raw BOILER file remains external and immutable:

- bytes: `3,361,935`;
- SHA-256: `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`.

## Recomputed current inventory

The current result still has 147 unique mismatch slots across 39 leaves, but
the independently recomputed family partition is:

| Current family | Slots | Roots | Interpretation |
|---|---:|---:|---|
| `G2-RC01` | **144** | 10 leaves / 22 first-divergence fields | multi-resource calendar-union strong candidate |
| `G2-RC03` | **3** | 2 leaves / 3 first-divergence fields | proven elapsed-duration float origin |
| `G2-RC02` | **0** | 0 | closed for the bounded measured production semantic |
| `G2-RC04` | **0** | 0 | no current compound slot |

Current roles are 25 `FIRST_DIVERGENCE`, 120 `DEPENDENT` and 2 `DERIVED`.
The field distribution remains:

| Field | Slots |
|---|---:|
| Start | 21 |
| Finish | 27 |
| Early Start | 21 |
| Early Finish | 27 |
| Late Start | 15 |
| Late Finish | 6 |
| Total Float | 21 |
| Free Float | 7 |
| Critical | 2 |

The ten current RC01 root leaves are `L0070`, `L0075`, `L0080`, `L0083`,
`L0084`, `L0114`, `L0127`, `L0148`, `L0157` and `L0190`. All ten are freshly
confirmed as automatic, unstarted, positive working-duration, ASAP tasks with
ordinary zero-lag FS logic on both sides, two assignments, two distinct resource
calendars and the explicit `ACTIVITY_RESOURCE_CALENDARS_UNITED` assumption.

The two current RC03 roots remain `L0407` and `L0411`.

The former historical RC04 slot is `L0084.Total Float`. Current replay closes
its source-coordinate calculation through two RC01 paths — `L0080 -> L0084`
and the local `L0084` root — so it is now an RC01 `DEPENDENT` consequence. The
historical record remains unchanged; this record supersedes only its use as a
description of current production.

RC01 remains `STRONG_CANDIDATE`, not proven. RC03's mismatch origin remains
`PROVEN`, but its replacement semantic remains `NOT_ESTABLISHED`. No BOILER
RC01 counterfactual or production RC01 correction is authorized.

## Exact RC01 native matrix

The next experiment is fixed before native execution:

`P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1`

Committed input:

- path: `tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1.xml`;
- bytes: `20,989`;
- SHA-256: `9d7ad7a8a845fcf036827fe90b51d41431d0452ece57097ce86934bec8119313`;
- project GUID: `01010101-0101-4101-8101-010101010101`;
- project start: `2026-10-12T08:00:00`.

The generator is
`scripts/evidence/p1_g2_rc01_assignment_native_generate.py`. Its exact bytes and
hash are pinned by tests.

### Fixed scheduling inputs

All four tasks are independent automatic ASAP tasks with no constraints,
progress, predecessors, explicit task calendar or levelling delay. Each is:

- MSPDI task `Type 0` / canonical `fixed_units`;
- non-effort-driven;
- `IgnoreResourceCalendar = 0`;
- four working hours duration;
- start `2026-10-12 08:00`;
- each assignment has four hours Work and Units `1.0`.

The project calendar is Monday-Friday, `08:00-12:00` and `13:00-17:00`.
Resources cannot participate in levelling (`CanLevel = 0`), and the task and
assignment levelling delays are zero. The experiment does not ask the operator
to invoke Resource Leveling.

The exact cases are:

| Case | Resource calendars | XML assignment order | Discriminator |
|---|---|---|---|
| A | AM `08:00-12:00`; PM `13:00-17:00` | AM, PM | assignment envelope is `08:00-17:00`; current union placement of four hours is `08:00-12:00` |
| B | same calendars and values as A | PM, AM | must reproduce A despite reversed declaration order |
| C | two distinct calendars, both `08:00-12:00` | first, second | overlapping two-resource control; envelope and union both end at `12:00` |
| D | one AM calendar `08:00-12:00` | one assignment | existing single-resource rule control |

This shape mirrors the current roots' fixed-units, non-effort-driven assignment
arithmetic while making the competing predictions mechanically distinct.

### Import and model boundary checked before design freeze

The current importer/migration was executed against the generated bytes:

- Assignment Work, Units, Start and Finish become canonical fields;
- resource calendar identity survives canonical migration;
- task Type becomes canonical `DurationType.fixed_units`;
- EffortDriven is preserved in the raw opaque vendor extension while the
  canonical value is false; and
- IgnoreResourceCalendar is also preserved in the opaque extension; its clear
  value maps to the canonical false semantic, while a set value would be
  promoted to the activity source field.

The analyzer therefore validates the raw MSPDI values that define the native
experiment and does not assume every vendor switch has a dedicated canonical
field.

## Predeclared returned-file analyzer

`scripts/evidence/p1_g2_rc01_assignment_native.py` was written before a native
return existed. Before classifying any observation it fails closed on changes
to:

- project, task, resource or assignment identity;
- any referenced calendar or working interval;
- task Type, EffortDriven, IgnoreResourceCalendar, duration, start, task
  calendar, constraint, progress or levelling inputs;
- assignment Work, Units, task/resource references or declaration order; and
- the zero-relationship topology.

It reads only the predeclared task Start/Finish/Early Start/Early Finish and
assignment Start/Finish observations after those inputs pass. A genuine native
build number is required. The unchanged generated input is classified
`NOT_RUN_UNRECALCULATED_INPUT` and authorizes nothing.

The possible results are fixed:

- `ASSIGNMENT_ENVELOPE_SUPPORTED`: all assignment spans fit their own resource
  calendars, A/B equal their assignment envelopes, A/B are order-independent,
  C/D pass and A/B differ from the union prediction;
- `ASSIGNMENT_ENVELOPE_REJECTED`: controls and order twin pass, but A/B do not
  equal their assignment envelopes; or
- `NATIVE_RESULT_INCONCLUSIVE`: a control fails, order matters or observations
  are mixed.

Only the supported result may authorize a **later diagnostic-only BOILER
counterfactual**. No native result from this matrix directly authorizes a
production scheduler correction.

## Required Microsoft Project run

Native execution has not occurred in this environment.

1. Open the exact committed XML in Microsoft Project desktop.
2. Do not edit tasks, resources, calendars, assignments or calculation options,
   and do not invoke Resource Leveling.
3. Recalculate the complete project (`F9` / Calculate Project).
4. Save the recalculated project back to MSPDI XML as
   `P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1-RETURNED.xml`.
5. Return that XML without opening or resaving it in another application.

Analyze the return with:

```bash
python3 scripts/evidence/p1_g2_rc01_assignment_native.py \
  P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1-RETURNED.xml \
  --output /separate/path/p1-g2-rc01-native-result.json
```

The native input and return remain immutable; analyzer output must be a separate
file.

## Evidence publication safety

The post-RC02 review command now requires the external baseline and refuses
output/check paths that are the baseline, either pinned evidence input, a
normalized `..` alias, a symlink alias or a hard-link alias. It writes a complete
sibling temporary file, flushes and fsyncs it, revalidates aliases immediately
before publication, atomically replaces the destination and fsyncs the parent
directory. Both source evidence records remain byte-identical.

Reproduce the committed sanitized review with:

```bash
python3 scripts/evidence/p1_g2_post_rc02_review.py \
  "$STO_BOILER_BEFORE" \
  --check docs/evidence/p1-g2-post-rc02-review-2026-09-25.json
```

## Gate consequence

- P1-G1 — PASS
- **P1-G2 — OPEN**
- P1-G3 — PASS
- P1-G4 — PASS
- P1-G5 — PASS
- P1 — **4/5, IN PROGRESS**
- P2 — **NOT STARTED**

Next action: run and return the exact synthetic RC01 matrix. Do not implement an
RC01 production semantic before the native result and a separately reviewed
BOILER counterfactual.
