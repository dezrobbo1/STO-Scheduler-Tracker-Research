# P1-G2 RC02 latest-successor BOILER counterfactual — 2026-09-25

Status: **DIAGNOSTIC COMPLETE — LATEST-SUCCESSOR COUNTERFACTUAL SUPPORTED**

This is a new bounded diagnostic following the completed inactive fan-out native
experiment. It does not reinterpret that experiment's failed combined stopping
rule and does not change production scheduling semantics.

## Evidence basis

The merged fan-out native evidence is pinned at
`docs/evidence/p1-g2-rc02-inactive-fanout-native-result-2026-09-25.json`.
Microsoft Project build `16.0.20326.20140` passed all controls and measured three
facts on the tested zero-lag-FS inactive fan-out shape:

1. forward placement bypasses inactive duration;
2. predecessor Late Finish matched the **latest** active-successor Late Start in
   all three deliberately reversed pairs; and
3. the Free-Slack sentinel changed from `12345` to `0`, matching the original
   inactive-edge gap rather than either direct-successor gap.

That experiment's own combined authorization remained false because its
predeclared active/inactive predecessor late-delta condition did not hold. This
counterfactual is therefore a **separate hypothesis declared after that result**,
not a retroactive change to the earlier experiment.

The prior BOILER direct-splice counterfactual is also pinned. It moved the fixed
422-slot inventory to 166 slots and RC02 from 258 to 19, with every remaining
RC02 path rooted at the `L0055 -> inactive L0052 -> {L0056,L0060}` fan-out.

## Predeclared directional transform

The exact BOILER baseline and fixed 422-slot inventory remain unchanged.
Production code remains unchanged.

The diagnostic has two directional halves because the measured native behavior
cannot be expressed by the current production `Network` relationship model:

### Forward

Add the same three zero-lag active-to-active diagnostic splices used by the prior
counterfactual:

- `L0055 -> L0056` across inactive `L0052`;
- `L0055 -> L0060` across inactive `L0052`;
- `L0400 -> L0389` across inactive `L0388`.

Run the unmodified production forward pass over that full network.

### Backward

First run the ordinary production backward pass over the full-splice network to
obtain each candidate active successor's Late Start. Before selecting anything,
**every candidate calculated Late Start must equal the immutable BOILER source
Late Start**; otherwise this diagnostic fails closed.

For each inactive boundary select the unique candidate with the latest Late
Start. Ties fail closed. On the pinned BOILER fixture the predeclared selected
set is:

- fan-out `L0055 -> L0052`: select `L0060`, not `L0056`;
- single successor `L0400 -> L0388`: select `L0389`.

The diagnostic backward pass then reuses the current production backward bound,
placement, driver and fingerprint helpers over the same full network, but omits
only the synthetic `L0055 -> L0056` edge from the predecessor's backward bound
scan. It does **not** remove that edge from forward placement or from the network
used by float analysis.

A fidelity guard runs the same wrapper with no omitted edges and requires its
late coordinates and metadata to equal ordinary production `backward_pass`
exactly. This makes the relationship filter the only intended semantic delta.

The existing source-observation Free-Slack guard must also pass. On the exact
BOILER fan-out, predecessor source Free Float, the inactive-edge gap and both
direct-successor early gaps are all zero, so the backward-edge selection cannot
silently substitute a different Free-Slack shape.

## Predeclared acceptance

The diagnostic succeeds only if all of the following hold:

1. current production reproduces the exact fixed **422-slot** inventory;
2. the prior symmetric direct-splice stage reproduces **166** total slots and
   **19 RC02** slots;
3. the merged native latest-successor evidence identity and components verify;
4. every candidate successor Late Start is source-aligned before selection;
5. the unfiltered diagnostic backward wrapper equals production backward pass;
6. the latest-successor directional run introduces **zero new mismatch slots**;
7. no non-RC02 family worsens;
8. all five RC02 first-divergence roots close;
9. all **258 RC02 slots** close, with no RC02 worsening; and
10. the exact prior 19-slot RC02 residue is the set removed by the new backward
    selection.

If and only if all ten conditions pass, the result may authorize a **separate,
bounded production RC02 correction PR**. It does not itself change production,
close P1-G2, make P1 5/5 or start P2. The full G2 inventory must be rerun after
any production correction, and other root-cause families remain independent.

## Reproduction

The raw BOILER fixture remains external and hash-pinned. Run:

```bash
PYTHONPATH=src:. python3 \
  scripts/evidence/p1_g2_rc02_latest_successor_boiler_counterfactual.py \
  "$STO_RC02_BOILER_BASELINE" \
  --output /outside-the-repository/p1-g2-rc02-latest-successor-result.json
```

To check a committed result without rewriting it:

```bash
PYTHONPATH=src:. python3 \
  scripts/evidence/p1_g2_rc02_latest_successor_boiler_counterfactual.py \
  "$STO_RC02_BOILER_BASELINE" \
  --check docs/evidence/p1-g2-rc02-latest-successor-boiler-counterfactual-2026-09-25.json
```

The tool refuses output/check paths that alias the private baseline.

## Measured result

The transform and acceptance rule were first committed at `4097d27efb723fc0c460bf0dd490687f70ea2bd0`.
Commit `1cf0660801be86caa645338764e1ab857e09efe0` corrected only the pinned byte identity of the already-merged native evidence file. The exact tool at that corrected pre-result head was then run against the hash-pinned BOILER baseline. The baseline remained byte-identical before and after execution.

The three stages are:

| Stage | Mismatch slots | Affected leaves | RC02 slots |
|---|---:|---:|---:|
| Production | 422 | 105 | 258 |
| Prior symmetric direct splice | 166 | 48 | 19 |
| Latest-successor directional | **147** | **39** | **0** |

The latest-successor selection was:

- `L0055 -> inactive L0052`: candidate Late Starts are `L0056 = 2026-09-17 05:00` and `L0060 = 2026-09-17 08:30`; both already equal their source observations, and `L0060` is selected as the unique latest successor.
- `L0400 -> inactive L0388`: the only candidate is `L0389 = 2026-09-24 15:00`, also source-aligned.

Suppressing only the synthetic `L0055 -> L0056` relationship from the backward
bound scan closes the exact 19-slot residue left by the prior symmetric
counterfactual. No other symmetric-stage mismatch changes. Across the original
422-slot inventory:

- `G2-RC02`: **258 closed, 0 remain**;
- `G2-RC01`: 17 closed, 11 improved, 132 unchanged, 0 worsened;
- `G2-RC03`: 3 unchanged;
- `G2-RC04`: 1 improved;
- new mismatch slots: **0**.

All five RC02 first-divergence roots close. The diagnostic wrapper with no
filtered relationship reproduces ordinary production `backward_pass` exactly,
so the single backward relationship filter is the isolated semantic change.
The source-observation Free-Slack guard remains green.

Every predeclared acceptance condition passes. The result is therefore:

`RC02_LATEST_SUCCESSOR_COUNTERFACTUAL_SUPPORTED`

and it authorizes the **next separate bounded production RC02 correction PR**.
This evidence PR does not itself modify production scheduling.

The remaining fixed inventory after the diagnostic is 147 slots: 143 `G2-RC01`,
3 `G2-RC03`, and 1 `G2-RC04`. Therefore P1-G2 is still open and P1 remains 4/5.
After the production RC02 correction, the exact BOILER inventory and the real-file
forward/backward/conformance cohorts must be rerun before moving to the remaining
root-cause families.

Sanitized exact result:
`docs/evidence/p1-g2-rc02-latest-successor-boiler-counterfactual-2026-09-25.json`.
