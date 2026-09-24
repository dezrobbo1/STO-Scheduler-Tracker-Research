# P1-G2 RC02 inactive fan-out native experiment — 2026-09-25

Status: **NATIVE RETURN ANALYZED — LATEST SUCCESSOR OBSERVED; PREDECLARED AUTHORIZATION NOT MET**

This is the bounded follow-up to
`p1-g2-rc02-boiler-counterfactual-2026-09-24.md`. It changes no production
scheduler, importer, canonical model, API, UI, gate or BOILER fixture.

## Question

The BOILER counterfactual closed 239 of 258 RC02 mismatch slots but left 19
slots on nine leaves. Every remaining RC02 dependency path roots at the active
predecessor of one inactive row that fans out to two active successors. The
one-successor native matrix did not measure that backward shape.

This experiment asks what Microsoft Project does for exactly:

`one active predecessor -> one inactive middle -> two active successors`

with zero-lag FS relationships, especially when the two successors have
different Late Start boundaries.

The experiment also retains a non-zero Free-Slack sentinel so unchanged import
retention cannot masquerade as a recalculated fan-out observation.

## Deterministic input

Generate the input with:

```bash
python3 scripts/evidence/p1_g2_rc02_fanout_native_generate.py \
  P1-G2-RC02-Inactive-Fanout-Native-Matrix.xml
```

Pinned identity:

- bytes: **64,729**
- SHA-256: `402bf7a9a143f7958fdf76589e7d566c2c0b84fa7593c4a06098e4fb29ed00b2`
- project name: `P1-G2-RC02-Inactive-Fanout-Native-Matrix.xml`
- calendar: synthetic 24-hour calendar
- project finish driver: 336 hours
- matrix tasks: 31

The file is fully synthetic. Raw customer schedule data is not used.

## Matrix design

Every experiment has an all-active control and an inactive-middle twin.

### Pair A — visible fan-out pass-through, S1 is the earlier late boundary

Active twin:

`PRED(24h) -> MID(48h) -> S1(96h)`

`                     -> S2(24h)`

Inactive twin has the same topology with `MID` inactive.

With the middle row active, both successors must start after its 48-hour
duration. If the previously measured zero-duration pass-through extends to a
fan-out, both inactive-twin successors should instead start at PRED Finish.

S1 is deliberately longer than S2, so its Late Start is earlier. This makes the
backward winner observable.

### Pair B — BOILER-shaped mixed fan-out, S2 is the earlier late boundary

Active twin:

`PRED(24h) -> MID(48h) -> S1(24h)`

`                     -> S2(96h)`

`OTHER(96h) -----------> S2`

The inactive twin is identical except `MID` is inactive.

This mirrors the unresolved BOILER shape more closely: one active successor has
only the inactive incoming path, while the other also has an ordinary active
predecessor. S2 has the earlier Late Start, reversing the winning successor from
Pair A. That reversal distinguishes an earliest-boundary rule from a fixed
successor/order artefact.

### Pair C — Free-Slack discriminator

Active and inactive twins use:

`PRED(24h) -> MID(48h) -> S1(24h)` with `O1(96h) -> S1`

`                     -> S2(48h)` with `O2(120h) -> S2`

Both ordinary predecessors drive their successors later than PRED Finish. This
creates distinct observable values in the inactive twin:

- original PRED -> inactive MID early gap: `0`;
- PRED -> S1 direct early gap: `43200` MSPDI slack units;
- PRED -> S2 direct early gap: `57600` MSPDI slack units.

`RC02-FO-C-I-PRED` is seeded with `FreeSlack=12345`, which matches none of those
candidate values. A returned `12345` therefore means unchanged sentinel
retention; it cannot support a Free-Slack conclusion.

## Predeclared interpretation

The analyzer validates all 31 task identities, Active flags, fixed durations,
zero-lag FS topology, dates and slack fields before classifying the result. Its
all-active controls must also reproduce ordinary fan-out forward and backward
behavior.

The fan-out backward observation is classified separately from Free Slack:

- predecessor Late Finish equal to the **earliest** active successor Late Start
  in A, B and C -> `EARLIEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED`;
- equal to the **latest** successor in all three ->
  `LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED`;
- equal to S1 in all three -> `S1_SUCCESSOR_LATE_BOUNDARY_OBSERVED`;
- inconsistent observations ->
  `NO_SINGLE_TESTED_FANOUT_BACKWARD_RULE_ESTABLISHED`.

The Pair C sentinel is classified independently:

- changed and equal to inactive-edge gap `0`, not direct successor minimum
  `43200` -> `SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP`;
- unchanged `12345` -> `SENTINEL_RETAINED_NOT_ESTABLISHED`;
- changed to direct-successor minimum ->
  `SENTINEL_CHANGED_MATCHES_DIRECT_SUCCESSOR_MIN_GAP`;
- any other value remains observational only.

Only the following combined result authorizes a **diagnostic-only BOILER
counterfactual rerun**:

1. all-active controls pass;
2. the fan-out forward pass-through controls pass;
3. all three inactive predecessors use the earliest active-successor Late Start;
4. the active/inactive predecessor late delta equals the removed 48-hour middle
   duration in all three pairs; and
5. the Pair C sentinel changes and matches the inactive-edge gap rather than the
   direct-successor gap.

Even that result does **not** authorize a production scheduler change, close
P1-G2, make P1 5/5 or start P2. It only supplies the missing bounded native rule
for one more BOILER diagnostic run.

## Native execution

Use the exact pinned generated input above.

1. Open `P1-G2-RC02-Inactive-Fanout-Native-Matrix.xml` in Microsoft Project.
2. Recalculate the project.
3. Save a **separate XML return**. Do not edit task data or relationships.
4. Return that saved XML for analysis.

The returned XML must remain outside the repository. The analyzer records its
size/hash and Project build while retaining a sanitized observation record.
Input lineage is owner-confirmed separately: the return hash alone cannot prove
which source file was opened.

Analyze a returned file with:

```bash
python3 scripts/evidence/p1_g2_rc02_fanout_native.py \
  /path/to/RETURNED.xml \
  --confirm-opened-input \
  --output /outside-the-repository/p1-g2-rc02-fanout-result.json
```

The tool refuses an output path that aliases the returned XML, including
resolved paths, symbolic links and hard links.

## Native return result — 2026-09-25

Owner supplied the Microsoft Project XML return produced from the pinned input.

Return identity:

- bytes: **183,947**
- SHA-256: `0f98ca5ac372e0929f17d9f0f563b0631ddb4786f3d1af476df4af941087547d`
- Microsoft Project build: `16.0.20326.20140`
- returned project name: `P1-G2-RC02-Inactive-Fanout-Native-Matrix - Returned.xml`

Input lineage remains explicit rather than inferred from the return hash: the owner
supplied this file in direct response to the pinned native-run request. The
returned bytes alone cannot prove which source file was opened.

All fixed-input, task-identity, Active-flag, zero-lag-FS topology, date/slack and
all-active control checks pass. The deliberately distinct inactive successor late
boundaries also remain intact, so the backward discriminator did not collapse.

Measured components:

- forward semantic:
  `ZERO_DURATION_FANOUT_FORWARD_PASSTHROUGH_SUPPORTED`;
- backward observation:
  `LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED`;
- Free-Slack observation:
  `SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP`.

The backward result is consistent across all three deliberately reversed pairs:

| Pair | Inactive PRED Late Finish | S1 Late Start | S2 Late Start | Match |
|---|---|---|---|---|
| A | 2026-10-25 08:00 | 2026-10-22 08:00 | 2026-10-25 08:00 | latest = S2 |
| B | 2026-10-25 08:00 | 2026-10-25 08:00 | 2026-10-22 08:00 | latest = S1 |
| C | 2026-10-25 08:00 | 2026-10-25 08:00 | 2026-10-24 08:00 | latest = S1 |

Because the winner flips between S1 and S2, this is not a fixed-successor or
declaration-order observation. In this bounded matrix the inactive predecessor
Late Finish matches the **latest** active-successor Late Start.

Pair C also resolves the sentinel question:

- seeded UID 26 FreeSlack: `12345`;
- returned FreeSlack: `0`;
- inactive-edge gap: `0`;
- direct S1 gap: `43200`;
- direct S2 gap: `57600`.

Unchanged sentinel retention is therefore ruled out on build
`16.0.20326.20140`, and the returned value matches the inactive-edge gap rather
than either direct-successor gap.

The combined predeclared authorization rule nevertheless **does not pass**.
The active/inactive predecessor Late-Finish deltas are:

- Pair A: `72000` MSPDI units;
- Pair B: `72000` MSPDI units;
- Pair C: `43200` MSPDI units.

The predeclared criterion required `28800` units (the removed 48-hour MID
duration) in all three pairs. Therefore the committed analyzer correctly retains:

`FANOUT_NATIVE_RULE_NOT_ESTABLISHED`

and:

- `boiler_counterfactual_rerun_authorized = false`;
- `production_scheduler_change_authorized = false`;
- `p1_g2_closed = false`;
- P1 remains `4/5 IN PROGRESS`;
- P2 remains not started.

The sanitized exact analyzer result is committed at
`docs/evidence/p1-g2-rc02-inactive-fanout-native-result-2026-09-25.json`.
Its retained observations are sufficient to rerun the classifier without the raw
XML, while an optional external-return test checks exact byte-for-byte analyzer
reproduction when the private return is supplied.

A later task may define a **new, separately predeclared diagnostic** based on the
newly observed latest-successor boundary. This experiment does not retroactively
broaden its stopping rule and does not itself authorize that BOILER rerun.

## Stopping rule

Do not modify production RC02 scheduling semantics in this experiment PR.

The valid native return has now been analyzed. The predeclared combined
authorization rule did not pass, so:

- P1-G2 remains **OPEN**;
- P1 remains **4/5, IN PROGRESS**;
- P2 remains **NOT STARTED**;
- this experiment does **not** authorize another BOILER counterfactual;
- no production RC02 correction is authorized.
