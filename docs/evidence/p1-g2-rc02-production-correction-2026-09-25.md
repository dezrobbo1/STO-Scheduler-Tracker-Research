# P1-G2 RC02 bounded production correction — 2026-09-25

Status: **PRODUCTION CORRECTION VERIFIED — RC02 CLOSED IN PRODUCTION; P1-G2 REMAINS OPEN**

This is the bounded production follow-up authorized by
`p1-g2-rc02-latest-successor-boiler-counterfactual-2026-09-25.md`.
It implements only the native-evidence-derived inactive-boundary behavior measured
for the supported zero-lag FS shape and then reruns the exact BOILER G2 inventory.

It does **not** broaden the rule to other relationship types, non-zero lag,
consecutive inactive rows, progressed endpoints, constrained/manual endpoints or
ambiguous fan-out. Unsupported inactive shapes remain explicitly labelled rather
than being silently scheduled under the new rule.

## Production basis

Fresh main before the correction:

`26dc06b6352fd882fa32f6b60a03eddd9b2b3f68`

Final production-source commit for this correction:

`55a27c99d0ca031890221c66ec4e0d8ede059690`

Production source identity:

- source digest: `3f80c59c7ff807d7d08803cb6f6697ce95f657da9aa15ee3c41586a70f4224d3`;
- pinned production path-tree SHA-256: `f7ca47d7e71f9c1e92fd13eaf2b02f351ffb8ca5a8fbb707c51aacb8b8a2ef11`;
- `BACKWARD_PASS_PROFILE`: `sto-backward-pass-v8`;
- `CRITICALITY_PROFILE`: `sto-criticality-v7`;
- `VALIDATOR_PROFILE`: `sto-validator-v4`.

The P1-G2 execution helper now names this final production basis, so later
root-cause evidence cannot accidentally execute against the pre-correction
scheduler while claiming current-main lineage.

## Bounded production semantic

The plan still excludes the inactive activity itself and the raw relationships
whose endpoint is inactive. For the measured subset only, it derives explicit
active-to-active zero-lag FS boundary relationships carrying the inactive
activity identity.

The supported subset requires:

- exactly one scheduled active predecessor of the inactive row;
- one or two scheduled active successors;
- ordinary zero-lag FS relationships on both sides;
- automatic, unprogressed, unconstrained active endpoints;
- an automatic, unprogressed, ordinary inactive task;
- no second inactive predecessor on the same successor; and
- no ambiguous reuse of one active predecessor across several supported inactive
  boundaries.

Anything outside that boundary retains the existing
`ACTIVITY_SUCCESSOR_OF_INACTIVE` assumption path.

### Forward

Every derived boundary relationship participates normally in the production
forward pass. The inactive duration therefore does not delay the active
successor, matching the bounded native matrix.

### Backward

Derived relationships sharing one inactive-boundary identity are evaluated as a
single measured fan-out group. With one active successor that successor binds.
With two successors, the unique **latest successor late boundary** binds the
active predecessor. An equal/tied late boundary fails closed with
`SCHEDULE_INACTIVE_BOUNDARY_LATE_TIE` rather than using declaration order.

### Free Slack and validation

For the supported zero-lag boundary, predecessor Free Slack retains the measured
inactive-edge reporting boundary of zero instead of using a later direct active-
successor gap. The real KILN file exposed why the validator needed the same
semantic: a derived active successor can tolerate a small movement even while
Microsoft's inactive-edge reporting boundary remains zero. Validator v4 therefore
checks the explicit inactive-boundary contract instead of applying the ordinary
"maximal movable slack" theorem to that edge.

The inactive-boundary identity participates in `Network.fingerprint()`, so a
network with this native-evidence-derived policy cannot hash as the ordinary
active-to-active graph.

## Exact BOILER verification

Raw BOILER schedule remains external.

- bytes: **3,361,935**;
- SHA-256: `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`.

The post-correction verifier reproduces the fixed historical 422-slot inventory,
runs current production and compares its complete 451-row nine-field projection
against the independently recorded PR #60 directional diagnostic.

Projection identity:

`e638c48a40fa572a1f98333b7628c15a1f9562203efc8c03c2a441f1d3ec0a73`

Remaining-key-set identity:

`bfb1b5113ac3f4adf8656a731935dee7387fcce95efb08ff601ce77fb38ed9ec`

Both identities match the supported counterfactual exactly.

| State | Mismatch slots | Affected leaves | RC02 slots |
|---|---:|---:|---:|
| Production before RC02 correction | 422 | 105 | 258 |
| Production after RC02 correction | **147** | **39** | **0** |

The remaining 147 slots are exactly:

| Group | Slots |
|---|---:|
| G2-RC01 | 143 |
| G2-RC03 | 3 |
| G2-RC04 | 1 |

No mismatch outside the fixed 422-slot inventory is introduced. The complete
sanitized remaining-slot list is retained in
`p1-g2-rc02-production-correction-2026-09-25.json`.

The exact production boundary set on BOILER is:

- `L0055 -> L0056` across inactive `L0052`;
- `L0055 -> L0060` across inactive `L0052`;
- `L0400 -> L0389` across inactive `L0388`.

Two BOILER inactive-successor rows remain outside the measured shape and retain
`ACTIVITY_SUCCESSOR_OF_INACTIVE`.

## Real-file regression

The same production code was run over BOILER, KILN and CALCINER.

### BOILER

Forward agreement improves from the pre-correction state to:

- Early Start: **430 / 451**;
- Early Finish: **424 / 451**;
- exact early span: **424 / 451**.

Late/float agreement becomes:

- Late Start: **436 / 451**;
- Late Finish: **445 / 451**;
- exact late span: **436 / 451**;
- Total Float: **430 / 451**;
- Free Float: **444 / 451**;
- Critical: **449 / 451**.

The source-coordinate Free-Slack rule explains **450 / 451** BOILER rows.

### KILN

The measured RC02 rule does not activate on KILN: its apparent candidate also
has a parallel direct relationship from the same active predecessor to the same
active successor, a shape not present in the native experiments. It therefore
remains explicitly labelled. The pinned date/late/float agreement counts remain
unchanged and the full validator is clean.

### CALCINER

No date, late, float or criticality agreement count changes. The full validator
is clean.

The production correction therefore closes the intended RC02 family on BOILER
without a regression in the two other real schedules used by this gate.

## Verification contract

Focused production regressions cover:

- one- and two-successor forward pass-through;
- latest-successor backward selection;
- reversal of the winning successor when the late ordering reverses;
- tied late boundaries fail closed;
- Free-Slack inactive-edge reporting semantics;
- validator acceptance of that reporting semantic;
- network fingerprint isolation;
- plan construction of measured boundary edges; and
- unsupported inactive shapes retaining the explicit assumption.

Post-correction evidence is generated by:

```bash
PYTHONPATH=src:tests:. python3 \
  scripts/evidence/p1_g2_rc02_production_verification.py \
  "$STO_RC02_PRODUCTION_BASELINE" \
  --check docs/evidence/p1-g2-rc02-production-correction-2026-09-25.json
```

The raw baseline is read-only and remains outside the repository.

## Gate decision

`G2-RC02` is now **closed in production** for the bounded measured semantic.
This does not close P1-G2 because 147 mismatches remain in the independent
families above.

Therefore:

- P1-G1 — PASS;
- **P1-G2 — OPEN**;
- P1-G3 — PASS;
- P1-G4 — PASS;
- P1-G5 — PASS;
- P1 — **4/5, IN PROGRESS**;
- P2 — **NOT STARTED**.

The next root-cause review should begin from this post-correction 147-slot
inventory. `G2-RC01` is now the dominant remaining family at 143 slots; its
cause and next bounded experiment/correction must be revalidated against current
production before any further scheduler change.
