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

`1982789f1c0aab83892dbac2f2d7b690ec9a85d6`

Production source identity:

- pinned production path-tree SHA-256: `a0ad82dfd2777c2acef2f5346e37e034f295e08c1992e6cd122bfc816a17b715`;
- `BACKWARD_PASS_PROFILE`: `sto-backward-pass-v8`;
- `CRITICALITY_PROFILE`: `sto-criticality-v7`;
- `VALIDATOR_PROFILE`: `sto-validator-v4`;
- `RESULT_PROFILE`: `sto-result-v3`.

The shared P1-G2 source execution helper now verifies this correction commit and
path-tree for current calculations. The immutable 2026-09-22 evidence record
continues to retain its original `0805bcb` lineage explicitly; its regression
asserts that historical value directly rather than conflating it with the
current execution basis. Current production evidence therefore fails closed on
stale source bytes without rewriting historical evidence.

## Bounded production semantic

The plan still excludes the inactive activity itself and the raw relationships
whose endpoint is inactive. For the measured subset only, it derives explicit
active-to-active zero-lag FS boundary relationships carrying the inactive
activity identity.

The supported subset requires:

- exactly one scheduled active predecessor of the inactive row;
- one or two scheduled active successors;
- ordinary zero-lag FS relationships on both sides;
- automatic, unprogressed, unconstrained, **non-elapsed** active endpoints;
- an automatic, unprogressed, ordinary inactive task;
- no second inactive predecessor on the same successor; and
- no active predecessor participating in more than one inactive boundary at all,
  counted from the raw inactive graph before per-boundary eligibility filtering.

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

Each derived boundary relationship is also projected into
`ScheduleResult.relationships` under
`RELATIONSHIP_NATIVE_INACTIVE_BOUNDARY_DERIVED`. Its deterministic detail
records the inactive activity, both original source relationship UIDs and the
active endpoints. Result profile `sto-result-v3` fingerprints that durable
lineage. On reload the workspace verifies the source relationships and inactive
row before accepting the derived relationship, so a published forward or late
driver UUID remains explainable after persistence/restart.

## Exact BOILER verification

Raw BOILER schedule remains external.

- bytes: **3,361,935**;
- SHA-256: `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`.

The post-correction verifier reproduces the fixed historical 422-slot inventory
and compares current production only with claims mechanically present in the
immutable merged PR #60 evidence. It requires exact equality with PR #60's
recorded **147-slot / 39-leaf by-field and by-group inventory summary** and its
full movement contract over all original 422 mismatch keys:

- RC01 — 17 closed, 11 improved, 132 unchanged;
- RC02 — 258 closed;
- RC03 — 3 unchanged;
- RC04 — 1 improved.

The verifier deliberately does **not** treat a projection hash first introduced
by this production PR as an independent oracle. It still records deterministic
current-production identities for replay/audit only:

- production projection SHA-256:
  `e638c48a40fa572a1f98333b7628c15a1f9562203efc8c03c2a441f1d3ec0a73`;
- production remaining-key-set SHA-256:
  `bfb1b5113ac3f4adf8656a731935dee7387fcce95efb08ff601ce77fb38ed9ec`.

Those two hashes identify this production result; they are not described as
independent PR #60 oracle values.

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
- plan construction of measured boundary edges;
- elapsed active endpoints retaining the explicit inactive-successor assumption;
- mixed eligible/ineligible inactive boundaries from one active predecessor
  retaining the explicit assumption for every branch;
- durable derived-driver lineage through result fingerprinting and persistence;
  and
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


## Review hardening — 2026-09-25

A fresh Codex-style review found four production/evidence integrity gaps. The
bounded correction was tightened without broadening its measured semantic:

1. elapsed active endpoints are now outside the RC02 rule, keeping RC03
   independent;
2. reuse of one active predecessor across several inactive rows is counted from
   the raw graph before eligibility, so a supported branch cannot coexist with
   an ignored unmeasured inactive branch;
3. synthetic boundary relationships now have durable, fingerprinted source-edge
   lineage in result profile `sto-result-v3`, verified again after reload; and
4. the verifier no longer calls production-created projection/key-set hashes an
   independent PR #60 oracle. Acceptance is based on PR #60's immutable
   inventory summary and movement contract.

The BOILER raw graph was rechecked after these guards were introduced. Its
supported RC02 boundaries remain exactly the three recorded above and none of
their active endpoints is elapsed, so the added scope guards do not change the
BOILER boundary cohort.