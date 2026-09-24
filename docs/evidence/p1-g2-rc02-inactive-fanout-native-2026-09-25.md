# P1-G2 RC02 inactive fan-out native experiment — 2026-09-25

Status: **INPUT READY — AWAITING OWNER-SUPPLIED MICROSOFT PROJECT RETURN**

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

## Stopping rule

Do not modify production RC02 scheduling semantics in this experiment PR.

Until a valid native return is analyzed:

- P1-G2 remains **OPEN**;
- P1 remains **4/5, IN PROGRESS**;
- P2 remains **NOT STARTED**;
- no production RC02 correction is authorized.
