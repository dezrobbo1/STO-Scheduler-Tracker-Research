# P1-G2 RC02 BOILER diagnostic counterfactual — 2026-09-24

Status: **PARTIAL SUPPORT — inactive fan-out backward behavior remains unmeasured**

This is a diagnostic-only real-file counterfactual for `G2-RC02`. It changes no
production scheduler, importer, canonical model, API, UI, gate, fixture or
Microsoft Project file.

## Basis

Fresh `main`: `43333a871916368359eb705e9080a9522e12db2b`, the merge of PR #57.

The diagnostic pins the production source it executes with SHA-256
`22e8bf15ed5181067b8294a0f6cb6b1b46d1612c216e8d11985284f5759ecac5`.
That digest covers `src/sto/core`, `src/sto/legacy`, the existing P1-G2 baseline
diagnostic and the controlled-transition field contract.

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| BOILER baseline | 3,361,935 | `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70` |
| Fixed 422-slot inventory | 376,346 | `2408fc99f282e9c600d3821b3c926f7deafa8c05044c7fec9a5f08b2b656bf63` |

The baseline remains external. The sanitized fixed inventory is
`p1-g2-baseline-root-causes-2026-09-22.json`.

## Counterfactual

PR #57 measured a bounded Microsoft Project rule for one active predecessor →
one inactive middle → one active successor, all zero-lag FS: active dates pass
through the inactive row with its duration removed. The Free-Slack observations
match the inactive-edge gap; the later sentinel rules out unchanged imported
sentinel retention on its tested build, without establishing a universal
Free-Slack formula.

The BOILER counterfactual does not change `build_plan`. It takes the production
network produced by fresh main and overlays synthetic zero-lag active → active FS
relationships only across exact one-hop active → inactive → active zero-lag FS
boundaries. It then reruns the existing forward pass, backward pass and float
analysis over that diagnostic network.

Exactly three synthetic relationships are introduced:

| Active predecessor | Inactive middle | Active successor |
|---|---|---|
| `L0055` | `L0052` | `L0056` |
| `L0055` | `L0052` | `L0060` |
| `L0400` | `L0388` | `L0389` |

The first inactive boundary fans out to two active successors. That fan-out was
**not** part of the native matrix and is explicitly an extrapolation for this
diagnostic. The second boundary is the measured one-successor shape.

For both BOILER boundaries, the diagnostic direct-successor Free-Slack gap and
the observed inactive-edge gap are both zero, so the direct diagnostic splice
does not create a Free-Slack distinction on these specific rows.

## Measured result

The production calculation reproduces the fixed baseline inventory exactly:
**422 mismatched field slots across 105 leaves**.

With only the diagnostic RC02 relationships overlaid:

| Measure | Before | After | Change |
|---|---:|---:|---:|
| All mismatch slots | 422 | 166 | -256 |
| Affected leaves | 105 | 48 | -57 |
| RC02 slots | 258 | 19 | -239 |
| RC02 affected leaves | 66 | 9 | -57 |
| New mismatch slots | 0 | 0 | 0 |

Original-family movement is:

| Family | Closed | Improved | Unchanged | Worsened |
|---|---:|---:|---:|---:|
| `G2-RC01` | 17 | 11 | 132 | 0 |
| `G2-RC02` | 239 | 15 | 0 | 4 |
| `G2-RC03` | 0 | 0 | 3 | 0 |
| `G2-RC04` | 0 | 1 | 0 | 0 |

No mismatch is created outside the original 422-slot inventory and no non-RC02
family worsens. The RC02 hypothesis nevertheless fails its own stopping rule:
four RC02 late-date slots worsen, and one RC02 first-divergence root remains
partial.

## Root outcomes

Four of five RC02 first-divergence roots close under the counterfactual:

- `L0056`: forward Start/Finish/Early Start/Early Finish close.
- `L0060`: forward Start/Finish/Early Start/Early Finish close.
- `L0389`: forward Start/Finish/Early Start/Early Finish close.
- `L0400`: predecessor Free Float closes.

`L0055` is only partial. Its Free Float closes, but its Late Start and Late
Finish remain mismatched. They move from `+649800` seconds to `-12600` seconds
relative to source — a large improvement but an overshoot rather than equality.
The remaining RC02 inventory contains 19 slots on nine leaves: nine Late Start,
nine Late Finish and one Total Float. Four dependent late-date slots worsen from
`+10800` to `-12600` seconds.

Every remaining RC02 dependency path roots at `L0055`, the active predecessor
of the one inactive row that fans out to **two** active successors. The separate
one-successor boundary rooted at `L0400` closes.

This localizes the unresolved dimension: the real-file result supports the
measured inactive pass-through strongly, but it does not establish how Microsoft
Project propagates the **backward/late boundary across an inactive row with
multiple active successors**.

## Decision

Classification:

`RC02_COUNTERFACTUAL_PARTIAL_SUPPORT_FANOUT_UNRESOLVED`

The counterfactual is **not successful** under the predeclared stopping rule:

- fixed 422-slot inventory reproduced — PASS;
- no new mismatch slots — PASS;
- no other family worsened — PASS;
- all RC02 first-divergence roots closed — **FAIL**;
- all RC02 paths non-worsening — **FAIL**.

Therefore this result does **not** authorize a production RC02 correction and
does **not** close P1-G2.

## Next bounded experiment

The next task is a small native Microsoft Project fan-out experiment, not a
production patch:

`active predecessor -> inactive middle -> two active successors`

Use zero-lag FS edges and deliberately distinct successor late boundaries so the
return distinguishes which successor, if any, governs the active predecessor's
Late Finish/Late Start across the inactive row. Retain a Free-Slack sentinel so
its observed reporting boundary remains independently visible.

Only after that fan-out behavior is measured should the BOILER counterfactual be
repeated with the newly bounded rule. A production semantic correction remains
out of scope until the RC02 roots and dependent paths close without worsening
other families.

## Reproduction

```bash
PYTHONPATH=src python3 scripts/evidence/p1_g2_rc02_boiler_counterfactual.py \
  "$STO_RC02_BOILER_BASELINE" \
  --check docs/evidence/p1-g2-rc02-boiler-counterfactual-2026-09-24.json
```

The tool hash-verifies the external BOILER baseline and fixed inventory, verifies
the fresh-main production source digest, refuses any moved splice set, rejects
new mismatch slots and leaves the baseline bytes unchanged.

## Gate consequence

P1 remains:

- P1-G1 — PASS
- P1-G2 — **OPEN**
- P1-G3 — PASS
- P1-G4 — PASS
- P1-G5 — PASS

P1 remains **4/5, IN PROGRESS**. P2 remains **NOT STARTED**.
