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

## Bounded Boiler v0.2 calculation trial

Use the exact external source identity and require a zero-difference admitted cohort for the recorded Phase 1.3 gate:

```bash
PYTHONPATH=src python scripts/run_external_calculation_trial.py \
  /absolute/path/to/boiler.xml \
  --output .external-results/boiler-v0.2/evidence.json \
  --expected-source-sha256 e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420 \
  --expected-canonical-sha256 e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6 \
  --require-zero-differences
```

The runner executes import, eligibility, projection, calculation, comparison and sanitized-evidence generation twice. It rejects source/output path collisions, unexpected source or canonical hashes, non-deterministic stage results and any admitted coordinate difference when `--require-zero-differences` is used.

The v0.1-to-v0.2 cohort comparison must be generated separately against base commit `641f32cc7cd1bc4d3f729fe0132122b19ec979ab`. Verify the regenerated v0.1 evidence is byte-identical to the committed v0.1.1 evidence before recording only counts and hashed ID sets. Raw IDs and full profile output remain external.

The reviewed sanitized v0.2 evidence is committed at:

```text
results/phase1/boiler-mspdi-import-and-calculation-evidence-v0.2.json
```

## Claim boundary

A successful import proves only that the source can be parsed into the declared canonical model deterministically and passes the repository's structural validator. It does not prove Microsoft Project scheduling-semantic or round-trip compatibility.

A zero-difference calculation trial proves only deterministic agreement with imported source Start/Finish observations for the admitted subset. It does not prove native Microsoft Project recalculation semantics, round-trip compatibility or production scheduling correctness.

Native evidence remains pending until an identified Microsoft Project desktop version and build opens a generated MSPDI file, recalculates it and produces a semantic comparison.
