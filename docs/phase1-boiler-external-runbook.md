# Phase 1 external Boiler MSPDI import runbook

The real Boiler XML is external test material and must not be committed to this public repository.

## Local execution

```bash
python -m pip install -e .
python scripts/run_external_mspdi_trial.py \
  /absolute/path/to/boiler.xml \
  --output-dir .external-results/boiler-v0.1
```

The command writes:

- `canonical.json` — full canonical representation; may contain source-sensitive names and values;
- `inventory.json` — sanitized structural inventory;
- `evidence.json` — source hash, counts, validation outcome and repeated-import hash evidence.

`.external-results/` is ignored. Only a manually reviewed, sanitized evidence record may be copied into `results/phase1/`.

## Claim boundary

A successful import proves only that the source can be parsed into the declared canonical model deterministically and passes the repository's structural validator. It does not prove Microsoft Project scheduling-semantic or round-trip compatibility.

Native evidence remains pending until an identified Microsoft Project desktop version and build opens a generated MSPDI file, recalculates it and produces a semantic comparison.
