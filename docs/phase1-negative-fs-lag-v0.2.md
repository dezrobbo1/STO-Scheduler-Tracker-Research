# Phase 1.3 — Negative elapsed-day FS lag experiment

Status: **merged on `main` via PR #13; bounded implementation and external Boiler evidence complete**

Related issue: #12

## Why this increment was selected

The merged Boiler v0.1 calculation evidence admits 226 of 460 activities. The primary exclusion counts are:

- `ACTIVITY_INACTIVE`: 9
- `DURATION_FORMAT_UNSUPPORTED`: 2
- `MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED`: 11
- `RELATIONSHIP_LAG_UNSUPPORTED`: 6
- `INELIGIBLE_PREDECESSOR`: 206

The 206 dependency-closure exclusions made the six unsupported lag links potentially high leverage: a small semantic addition could admit downstream chains without broadening unrelated scheduling behaviour.

## External Boiler lag inventory

A direct inspection of the external Boiler MSPDI source found exactly six non-zero predecessor lags. No task names, task IDs or source XML are committed here.

All six links are:

- relationship type: FS (`Type=1`);
- lag sign: negative (lead time);
- `LagFormat=8`.

Distinct raw `LinkLag` values and counts:

| LinkLag (tenths of a minute) | Elapsed duration represented | Count |
|---:|---:|---:|
| -403200 | -28 elapsed days | 2 |
| -302400 | -21 elapsed days | 1 |
| -100800 | -7 elapsed days | 1 |
| -86400 | -6 elapsed days | 1 |
| -28800 | -2 elapsed days | 1 |

## Authoritative semantic evidence

Microsoft's MSPDI documentation states that `LinkLag` is stored in **tenths of a minute** and that `LagFormat` specifies the time format of the lag.

Microsoft's `PjFormatUnit` documentation identifies numeric value `8` as `pjElapsedDays` — elapsed days.

Microsoft's `TaskDependency.LagType` documentation states that negative lag represents lead time.

Therefore the six Boiler cases can be classified, without guessing, as **negative FS lead expressed in elapsed days**.

This establishes the unit and sign semantics. It does not by itself prove every Microsoft Project scheduling interaction for negative elapsed-day lead.

## Implemented profile v0.2 boundary

The calculation profile is explicitly versioned as
`mspdi-calculation-eligibility-v0.2`; v0.1 was not silently widened.

Implemented support:

- existing v0.1 semantics unchanged;
- FS relationships with zero lag;
- FS relationships with negative lag only when `LagFormat=8` (`pjElapsedDays`);
- lag magnitude taken from canonical `lag_seconds`, which is derived from the authoritative MSPDI `LinkLag` tenths-of-a-minute value;
- exact consistency required between raw `LinkLag` and `lag_seconds` (`lag_seconds == LinkLag * 6`);
- elapsed lead applied as continuous wall-clock time from predecessor finish;
- non-milestone successor start then normalized through the successor's already-supported effective working calendar;
- project start anchors dependency-free roots but does not clamp a dependency-driven lead candidate;
- multiple predecessors select the latest lag-adjusted candidate;
- negative-lag milestone successors remain excluded;
- calendar exceptions remain permitted only when wholly outside the project, source-coordinate and supported lead-candidate horizon.

Remain unsupported:

- positive lag;
- non-elapsed lag formats;
- SS, FF and SF calculation;
- cross-project links;
- relationship extensions;
- progressed/status-date schedules;
- backward pass, late dates and float;
- resource levelling;
- MSPDI export;
- native Project compatibility claims.

## Regression coverage

Synthetic tests cover:

1. FS negative elapsed-day lead where the resulting instant is already in successor working time;
2. FS negative elapsed-day lead where the resulting instant lands outside successor working time and must normalize to the next supported working instant;
3. multiple predecessors where the lagged FS driver competes with a zero-lag driver;
4. positive elapsed-day lag remains excluded;
5. `LagFormat` values other than 8 remain excluded;
6. raw `LinkLag` / `lag_seconds` mismatch remains excluded;
7. a valid lead may place a successor before project start;
8. a calendar exception at a pre-project lead candidate fails closed;
9. stale/tampered profile provenance remains rejected;
10. a tampered engine projection cannot introduce a negative lag into a milestone.

## External Boiler v0.2 evidence

The exact external Boiler source was imported and the complete v0.2 pipeline was run twice:

```text
MSPDI import
  -> canonical v0.1.1
  -> calculation eligibility v0.2
  -> engine projection
  -> forward calculation
  -> source-coordinate comparison
  -> sanitized evidence
```

Source and import identity:

| Measure | Result |
|---|---:|
| Source SHA-256 | `e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420` |
| Canonical schema | `0.1.1` |
| Importer profile | `mspdi-import-v0.1.1` |
| Canonical SHA-256 | `e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6` |

All reproducibility checks passed across the two runs:

- canonical hashes equal;
- eligibility/profile evidence equal;
- profile SHA-256 equal;
- projection SHA-256 equal;
- calculation SHA-256 equal;
- coordinate-comparison evidence equal;
- sanitized evidence equal.

Measured cohort change against the regenerated and byte-verified merged v0.1 baseline:

| Measure | v0.1 | v0.2 | Change |
|---|---:|---:|---:|
| Eligible activities | 226 | 282 | +56 |
| Excluded activities | 234 | 178 | -56 |
| Eligible relationships | 253 | 327 | +74 |
| Excluded relationships | 347 | 273 | -74 |
| Eligible milestones | 24 | 27 | +3 |
| Eligible non-milestones | 202 | 255 | +53 |
| Compared activities | 226 | 282 | +56 |
| Exact Start/Finish matches | 226 | 282 | +56 |
| Coordinate differences | 0 | 0 | 0 |

The 56 newly eligible activities comprise the six direct negative elapsed-day FS-lead successors and 50 downstream dependency-closure activities. All 56 newly admitted activities reproduce their imported source Start/Finish coordinates exactly. No previously eligible activity or relationship was removed.

Reason-count change:

| Reason | v0.1 | v0.2 | Change |
|---|---:|---:|---:|
| `ACTIVITY_INACTIVE` | 9 | 9 | 0 |
| `DURATION_FORMAT_UNSUPPORTED` | 2 | 2 | 0 |
| `MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED` | 12 | 12 | 0 |
| `WORK_UNITS_INCONSISTENT` | 10 | 10 | 0 |
| `RELATIONSHIP_LAG_UNSUPPORTED` | 6 | 0 | -6 |
| `INELIGIBLE_PREDECESSOR` | 219 | 169 | -50 |

Primary `INELIGIBLE_PREDECESSOR` exclusions changed from 206 to 156. Primary `RELATIONSHIP_LAG_UNSUPPORTED` exclusions changed from 6 to 0. Other primary reason counts are unchanged.

## Difference analysis and corrections

The first v0.2 external calculation admitted 282 activities but produced 56 coordinate differences. All 56 were in the newly admitted cohort.

Classification: **calculation implementation defect**.

The engine incorrectly clamped every dependency-driven candidate to project start. The six source leads legitimately place successors before project start. The correction now uses project start only for dependency-free roots; dependency-driven activities use the latest lag-adjusted predecessor candidate before successor-calendar normalization.

An independent review also identified two fail-closed gaps and corrected them before recording the final evidence:

- the engine now rejects a tampered negative-lag relationship into a milestone;
- calendar exception overlap checks include supported pre-project lead candidates, preventing an ignored exception from affecting a lead calculation.

After correction, the two-run result is 282 compared, 282 exact matches and zero coordinate differences. No unexplained differences remain.

## Evidence hygiene

The committed evidence is:

```text
results/phase1/boiler-mspdi-import-and-calculation-evidence-v0.2.json
```

It records counts, reason tables, deterministic fingerprints, changed-cohort hashes, comparison results and the sanitized defect classification. It does not contain the source XML, canonical output, task or relationship IDs, task names, notes, work package names, resource names or source-derived descriptive data.

## Evidence interpretation

Three evidence classes remain distinct:

1. **Source semantic evidence:** the six source links are FS, negative, `LagFormat=8` elapsed-day leads with consistent raw and normalized lag values.
2. **Deterministic agreement:** the v0.2 engine reproduces the imported source Start/Finish observations for all 282 activities admitted by this bounded profile, including all 56 newly admitted activities.
3. **Native Microsoft Project validation:** **not executed**. No identified Microsoft Project desktop version/build recalculated this case.

## Claim boundary

The zero-difference Boiler result establishes only deterministic agreement with imported source Start/Finish observations for this declared subset and source. It does not establish full Microsoft Project scheduling semantics, native recalculation equivalence, round-trip compatibility, production scheduling correctness, P6 compatibility or general scheduler completeness.
