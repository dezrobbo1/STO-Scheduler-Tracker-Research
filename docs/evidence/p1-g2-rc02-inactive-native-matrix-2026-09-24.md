# P1-G2 RC02 inactive-activity native matrix — 2026-09-24

Status: **NATIVE EXPERIMENT COMPLETE — bounded zero-lag FS semantics measured**

This is a bounded causal experiment for `G2-RC02`. It changes no scheduler,
importer, canonical model, API, UI, gate or mismatch classification.

## Question

The current P1-G2 diagnosis assigns 258 mismatch slots to the
`STRONG_CANDIDATE` inactive-activity logic boundary. The existing engine drops
relationships whose inactive endpoint is not scheduled. A prior
zero-duration-inactive-node pass-through experiment made the BOILER comparison
worse and is not reused as an assumed production rule here.

The experiment asks what the current Microsoft Project desktop build does
across an inactive row for:

- active-successor forward placement;
- active-predecessor late placement; and
- active-predecessor Free Slack.

The native result establishes a bounded composite semantic for the tested
zero-lag FS shape. It does not establish a general rule for other relationship
types, lags, calendars, constraints, progress or consecutive inactive rows.

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
  inactive path from date pass-through on successor start.
- **Pair B — competing predecessor, inactive path later.** `PRED -> MID -> SUCC`
  plus `OTHER -> SUCC`, with `PRED` later than `OTHER`. If the inactive path is
  dropped, `OTHER` drives. If the inactive boundary passes the date through,
  `PRED` drives.
- **Pair C — competing predecessor, other path later.** `OTHER` drives the
  successor forward under either date hypothesis. `PRED` late finish tests the
  backward boundary. Free Slack then distinguishes an ordinary direct
  `PRED -> SUCC` splice from retention of the original `PRED -> inactive MID`
  reporting boundary.

This last distinction matters. The first analyzer version treated any
Free-Slack influence below Total Slack as sufficient proof of a direct splice.
The returned native values show that was too broad: Pair C retains a zero
Free-Slack boundary to the inactive middle row even though forward and late
dates pass through its duration. The classifier was corrected before the
experiment conclusion was recorded.

## Native execution

The owner opened the generated XML in Microsoft Project, recalculated it and
saved a separate XML return without editing the matrix.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Generated input | 48,322 | `ca4cbe0495180a232c4498998a4de94ab0d2863f4bd2f01cecd08cdf68b38024` |
| Project-saved return | 139,672 | `c245ef00b9ae71a9f901bb3775158c21dd87b88115e5e028656d176abda2d549` |

Returned Microsoft Project build: `16.0.20228.20188`.

The raw returned XML remains external evidence and is not committed.

Analyze it with:

`python3 scripts/evidence/p1_g2_inactive_native_matrix.py P1-G2-RC02-Inactive-Native-Returned.xml --output /tmp/p1-g2-rc02-native-result.json`

The committed JSON is the sanitized analyzer result, not the raw Project file.

## Native result

Verdict:

`ZERO_DURATION_DATE_PASSTHROUGH_WITH_INACTIVE_EDGE_FREE_SLACK`

The result separates two measured components.

### Date semantic — zero-duration FS pass-through supported

All three tested inactive chains show the inactive task's duration removed from
the active schedule boundary:

- Pair A inactive successor starts exactly at its active predecessor finish.
- Pair B inactive successor starts at the later active predecessor finish,
  rather than at the earlier ordinary predecessor finish.
- In Pairs A, B and C, the inactive-chain active predecessor Late Finish equals
  the active successor Late Start.

For the tested zero-lag FS shape, Project therefore preserves a forward and
backward date boundary across the inactive row while ignoring the inactive
row's duration.

### Free-Slack semantic — original inactive edge bound supported

Pair C deliberately creates a three-day early gap between the inactive-chain
active predecessor and the active successor. On the 24-hour matrix this is
43,200 MSPDI slack units.

Observed Pair C active-predecessor values:

- Free Slack: `0`
- Total Slack: `115200`
- gap to active successor Early Start: `43200`
- gap to inactive middle Early Start: `0`

Therefore Free Slack is **not** the ordinary direct-splice gap to the active
successor. It remains bounded by the original edge to the inactive middle row
in this tested shape.

This is why the experiment does not resurrect the previously rejected
"make the inactive task a zero-duration scheduled node" implementation. The
measured behavior is composite: date propagation bypasses inactive duration,
while Free Slack retains the original inactive-edge reporting boundary.

Microsoft's public Active-field documentation says inactive tasks no longer
affect other tasks or the overall plan, while retaining their dependencies for
possible reactivation. That high-level description is compatible with removing
the inactive duration from active date placement, but it does not specify the
Free-Slack reporting detail measured here. The native XML is the evidence for
that detail.

## Consequence for G2-RC02

The native experiment **proves the candidate boundary for this tested zero-lag
FS shape**, but it does not itself change production scheduling behavior or
prove how many of the 258 BOILER mismatch slots will close.

The next task is a separate diagnostic counterfactual over the exact BOILER
pair:

1. apply the measured date pass-through only to RC02 zero-lag FS inactive
   boundaries in diagnostic code;
2. preserve the measured original inactive-edge Free-Slack boundary;
3. rerun the fixed 422-slot inventory;
4. require the RC02 first divergences and dependent paths to move in the
   predicted direction without worsening other families; and
5. only then authorize one production semantic correction.

This satisfies the repository rule that a diagnosis must be measured against
the real data before changing production code.

## Stopping rule

Do not change production scheduling semantics in this experiment PR.

P1 remains:

- P1-G1 — PASS
- P1-G2 — OPEN
- P1-G3 — PASS
- P1-G4 — PASS
- P1-G5 — PASS

P1 remains **4/5, IN PROGRESS**. P2 remains **NOT STARTED**.
