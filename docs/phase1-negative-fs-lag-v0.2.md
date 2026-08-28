# Phase 1.3 — Negative elapsed-day FS lag experiment

Status: **active bounded semantic experiment**

Related issue: #12

## Why this is next

The merged Boiler v0.1 calculation evidence admits 226 of 460 activities. The primary exclusion counts are:

- `ACTIVITY_INACTIVE`: 9
- `DURATION_FORMAT_UNSUPPORTED`: 2
- `MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED`: 11
- `RELATIONSHIP_LAG_UNSUPPORTED`: 6
- `INELIGIBLE_PREDECESSOR`: 206

The 206 dependency-closure exclusions make the six unsupported lag links potentially high leverage: a small semantic addition may admit downstream chains without broadening unrelated scheduling behaviour.

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

## Proposed profile v0.2 boundary

The next calculation profile should be a new version rather than silently widening v0.1.

Proposed support:

- existing v0.1 semantics unchanged;
- FS relationships with zero lag;
- FS relationships with negative lag only when `LagFormat=8` (`pjElapsedDays`);
- lag magnitude taken from canonical `lag_seconds`, which is derived from the authoritative MSPDI `LinkLag` tenths-of-a-minute value;
- elapsed lead applied as continuous wall-clock time from predecessor finish;
- non-milestone successor start then normalized through the successor's already-supported effective working calendar;
- milestone behaviour tested separately and admitted only if synthetic/source evidence agrees.

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

## Required tests before Boiler evidence is accepted

Synthetic tests must cover at least:

1. FS negative elapsed-day lead where the resulting instant is already in successor working time;
2. FS negative elapsed-day lead where the resulting instant lands outside successor working time and must normalize to the next supported working instant;
3. multiple predecessors where the lagged FS driver competes with a zero-lag driver;
4. positive elapsed-day lag remains excluded;
5. `LagFormat` values other than 8 remain excluded;
6. stale/tampered profile provenance remains rejected.

## External acceptance test

After implementation, rerun the exact external Boiler source twice and compare against the merged v0.1 baseline:

- eligible activity count;
- eligible relationship count;
- exclusion reason counts;
- exact Start/Finish matches;
- coordinate differences;
- deterministic profile/projection/calculation fingerprints.

Any newly admitted activity with an unexplained Start/Finish difference blocks the semantic from being treated as supported.

## Claim boundary

Even a zero-difference Boiler result would establish only deterministic agreement with the imported source Start/Finish observations for this bounded source/profile. It would not establish Microsoft Project semantic compatibility. Native Project recalculation and round-trip evidence remain separate gates.
