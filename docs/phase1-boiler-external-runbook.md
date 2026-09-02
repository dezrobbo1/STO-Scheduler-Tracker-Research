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

The reviewed sanitized v0.2 evidence is committed at:

```text
results/phase1/boiler-mspdi-import-and-calculation-evidence-v0.2.json
```

## Reproducible profile-cohort comparison

Use the committed comparison generator instead of manually assembling the v0.1-to-v0.2 cohort delta.

Create a detached baseline worktree at the exact merged v0.1 calculation commit:

```bash
git worktree add .external-results/baseline-v0.1 \
  641f32cc7cd1bc4d3f729fe0132122b19ec979ab
```

Then run the same external source through both checkouts:

```bash
PYTHONPATH=src python scripts/compare_calculation_profiles.py \
  /absolute/path/to/boiler.xml \
  --baseline-root .external-results/baseline-v0.1 \
  --output .external-results/boiler-v0.1-to-v0.2/cohort-comparison.json \
  --expected-source-sha256 e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420 \
  --expected-canonical-sha256 e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6 \
  --require-zero-differences
```

The comparison runner:

- executes each checkout's import/profile/projection/calculation pipeline twice;
- requires both checkouts to produce the exact same canonical document;
- verifies candidate calculation coverage against the complete candidate eligible cohort;
- calculates added and removed activity/relationship sets;
- classifies direct negative elapsed-day FS-lead successors separately from downstream dependency-closure additions;
- writes counts and SHA-256 set fingerprints only;
- rejects arrays and raw canonical task/relationship IDs in the sanitized output.

The temporary pipeline payloads contain source-derived IDs and full canonical data. They remain inside a temporary directory and are deleted by the runner. Only the sanitized comparison output may be reviewed for possible inclusion in `results/phase1/`.

Remove the detached worktree when finished:

```bash
git worktree remove .external-results/baseline-v0.1
```

## Claim boundary

A successful import proves only that the source can be parsed into the declared canonical model deterministically and passes the repository's structural validator. It does not prove Microsoft Project scheduling-semantic or round-trip compatibility.

A zero-difference calculation trial proves only deterministic agreement with imported source Start/Finish observations for the admitted subset. It does not prove native Microsoft Project recalculation semantics, round-trip compatibility or production scheduling correctness.

A profile-cohort comparison proves only the measured difference between two declared repository calculation profiles against the same canonical source.

Native evidence remains pending until an identified Microsoft Project desktop version and build opens a generated MSPDI file, recalculates it and produces a semantic comparison.
