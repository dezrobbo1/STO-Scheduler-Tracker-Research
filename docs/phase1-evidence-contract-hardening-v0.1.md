# Phase 1.4 — Calculation evidence and projection contract hardening

Status: **active bounded hardening on issue #15**

## Purpose

Phase 1.3 established a zero-difference Boiler result for 282 activities under calculation profile `mspdi-calculation-eligibility-v0.2`.

This hardening phase does not add a scheduling semantic. It strengthens the research harness so later experiments cannot accidentally:

- compare an incomplete or duplicated calculated cohort;
- silently collapse duplicate projection identifiers;
- accept fractional-second values that the current engine does not preserve;
- build sanitized evidence from stale or tampered intermediate stages;
- rely on an undocumented manual process for profile-to-profile cohort comparison.

## Implemented contract changes

### Engine projection validation

The forward engine validates its projection before calculation.

Validation now rejects:

- duplicate calendar, activity or relationship identifiers;
- malformed project/source envelopes;
- invalid or drifted effective-calendar fingerprints;
- incomplete, unordered or overlapping weekly calendar intervals;
- missing activity calendars;
- non-ASAP constraints;
- milestone/duration disagreement;
- fractional or negative activity duration seconds;
- unsupported relationship types;
- missing relationship endpoints;
- positive or fractional lag seconds;
- inconsistent lag basis;
- negative lag into milestones.

The projection builder remains the normal source of engine input, but the engine no longer assumes that every caller used it.

### Exact comparison cohort

Source-coordinate comparison rebuilds the canonical eligibility profile and requires the calculated activity ID set to equal the complete eligible activity set.

The comparison rejects:

- omitted eligible activities;
- additional activities;
- duplicate calculated activity IDs;
- calculations from another canonical document.

The set comparison uses deterministic SHA-256 fingerprints and direct set equality.

### Evidence stage verification

`sanitized_profile_evidence()` independently rebuilds:

1. eligibility profile;
2. engine projection;
3. forward calculation;
4. source-coordinate comparison.

Optional caller-supplied stages are assertions only. Any supplied stage whose deterministic fingerprint differs from the recomputed stage is rejected.

### Integral-second boundary

The current profile now explicitly requires:

- activity duration seconds to be exact integers;
- relationship lag seconds to be exact integers.

This does not change the recorded Boiler cohort because its admitted values are integral. Fractional-second scheduling remains outside the current research boundary.

### Reproducible cohort comparison

`scripts/compare_calculation_profiles.py` runs one external source through two repository checkouts and produces a sanitized comparison.

It measures:

- added and removed eligible activities;
- added and removed eligible relationships;
- direct negative elapsed-day FS-lead successors;
- downstream dependency-closure additions;
- changed-cohort Start/Finish agreement;
- reason and primary-reason count deltas;
- deterministic profile, calculation and set fingerprints.

Raw IDs and source-derived descriptions remain external.

### Continuous integration

CI now runs:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src scripts tests
git diff --check
```

## Repository administration

Branch protection or a repository ruleset is an administrative GitHub setting rather than a repository file.

Recommended `main` rules remain:

- require a pull request;
- require the CI `test` job;
- require review-conversation resolution;
- block force pushes;
- block branch deletion.

This setting must be confirmed separately in GitHub administration. It is not represented as completed by this code change.

## Claim boundary

This hardening does not establish:

- Microsoft Project native recalculation equivalence;
- MSPDI export or round-trip compatibility;
- Primavera P6 compatibility;
- backward pass, late dates or float;
- positive lag, working-time lag or SS/FF/SF;
- progressed/status-date scheduling;
- resource levelling;
- production scheduling correctness.

The existing Phase 1.3 evidence remains a deterministic comparison with imported source Start/Finish observations only.
