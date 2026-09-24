# P1-G2 RC02 latest-successor BOILER counterfactual — 2026-09-25

Status: **PREDECLARED DIAGNOSTIC READY — RESULT NOT YET RECORDED**

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
