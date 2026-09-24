# P1-G2 RC02 inactive-activity native matrix — 2026-09-24

Status: **PREPARED — native Microsoft Project return required**

This is a bounded causal experiment for `G2-RC02`. It changes no scheduler,
importer, canonical model, API, UI, gate or mismatch classification.

## Question

The current P1-G2 diagnosis assigns 258 mismatch slots to the
`STRONG_CANDIDATE` inactive-activity logic boundary. The existing engine drops
relationships whose inactive endpoint is not scheduled. A prior
zero-duration-inactive-node pass-through experiment made the BOILER comparison
worse and is not reused here.

The experiment asks whether the current Microsoft Project desktop build applies
one consistent effective rule across an inactive row that predicts both:

- active-successor forward placement; and
- active-predecessor late/free-float influence.

The native result must establish or reject the candidate before any production
semantic changes.

## Synthetic matrix

Generate the input with:

`python3 scripts/evidence/p1_g2_inactive_native_matrix_generate.py P1-G2-RC02-Inactive-Native-Matrix.xml`

The deterministic input is 48,322 bytes with SHA-256
`ca4cbe0495180a232c4498998a4de94ab0d2863f4bd2f01cecd08cdf68b38024`.
It contains only synthetic tasks on a 24-hour calendar. Each experiment
has an all-active control and an otherwise identical twin whose middle task is
inactive. `RC02-FINISH-DRIVER` fixes the project finish independently so float
comparisons do not depend on which experimental chain finishes last.

- **Pair A — sole path.** `PRED -> MID -> SUCC`. This distinguishes a dropped
  inactive path from an effective direct zero-lag FS splice on successor start.
- **Pair B — competing predecessor, inactive path later.** `PRED -> MID -> SUCC`
  plus `OTHER -> SUCC`, with `PRED` later than `OTHER`. If the inactive path is
  dropped, `OTHER` drives. If Project creates an effective direct FS boundary,
  `PRED` drives.
- **Pair C — competing predecessor, other path later.** `OTHER` drives the
  successor under either forward hypothesis. The discriminator is the inactive
  chain's `PRED` Free Slack versus Total Slack: equality indicates no effective
  successor; Free Slack below Total Slack indicates successor influence remains.

This is intentionally not a general matrix for non-FS relationship types,
lags, constraints, progress, calendars, resources, or multiple consecutive
inactive activities. P1-G2 needs the smallest causal experiment that matches
the diagnosed zero-lag FS boundary first.

## Native procedure

Use the available Windows Microsoft Project desktop session.

1. Generate the input once and keep those exact bytes immutable.
2. Open `P1-G2-RC02-Inactive-Native-Matrix.xml` in Microsoft
   Project.
3. Confirm the three `*-I-MID` rows are inactive and the `*-A-MID` controls are
   active. Do not edit task dates, durations, links, constraints or calendars.
4. Run **Calculate Project** (`F9`).
5. Save **as a new XML file**, for example
   `P1-G2-RC02-Inactive-Native-Returned.xml`. Do not overwrite the input.
6. Record the Project build shown by the returned XML's `<BuildNumber>`.
7. Run:

   `python3 scripts/evidence/p1_g2_inactive_native_matrix.py P1-G2-RC02-Inactive-Native-Returned.xml --output /tmp/p1-g2-rc02-native-result.json`

Return the native XML and the JSON result. The XML remains external evidence and
must not be committed.

## Classification contract

The analyzer has three outcomes.

`DIRECT_ZERO_LAG_FS_SPLICE_SUPPORTED` requires all three independent
observations to agree:

- Pair A inactive successor starts at inactive-twin predecessor finish;
- Pair B inactive successor starts at the later inactive-twin predecessor
  finish rather than the earlier ordinary predecessor finish; and
- Pair C inactive-twin predecessor Free Slack is below Total Slack, showing
  backward/free-float influence even though the ordinary predecessor controls
  successor forward placement.

`DROP_BOTH_ENDPOINT_EDGES_SUPPORTED` requires:

- Pair A inactive successor returns to project start;
- Pair B inactive successor starts at the ordinary predecessor finish; and
- Pair C inactive-twin predecessor Free Slack equals Total Slack, as a task with
  no effective successor.

Any mixed result is `NO_SINGLE_TESTED_RULE_ESTABLISHED`. That outcome is
evidence too: it means RC02 cannot be replaced by one simple zero-lag FS
boundary semantic from this experiment.

The analyzer reports observations and predicates; it does not modify or
recalculate the returned schedule.

## Stopping rule

Do not change production scheduling semantics in this experiment PR.

After the native return:

- if one rule is established, record the native build, returned-file hash and
  result, then close this experiment PR as evidence;
- make any scheduler correction in a separate focused PR, rerunning the exact
  422-slot P1-G2 inventory and real-file forward/backward/conformance cohorts;
- if no single rule is established, retain P1-G2 OPEN and design the next
  smallest discriminating experiment rather than patching dates.

P1 remains 4/5 until P1-G2 itself passes.
