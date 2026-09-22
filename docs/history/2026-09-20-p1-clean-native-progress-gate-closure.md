# P1 clean native-progress gate closure — 2026-09-20

> **Superseded on 2026-09-21.** Review found that `UNCHANGED` did not require
> engine/source baseline equality. The corrected comparison exposes 422 static
> baseline field mismatches across 105 leaves. P1-G3 remains passed for the
> bounded native transition; P1-G2 and P1 are reopened. See
> `docs/history/2026-09-21-p1-gate-review-correction.md`.

## Decision

P1 is passed. The clean controlled Microsoft Project repeat satisfies P1-G2
and P1-G3 under the comparison contract committed before the native output
existed. P2 becomes the current roadmap phase but remains `not_started`; no P2
slice begins in this change, and the previously proposed limited S7/PL4
exception was not enacted.

## Evidence received

The repeat `P1-NATIVE-PROGRESS-BOILER-UID227-V1` used the verified
3,361,935-byte BOILER baseline with SHA-256
`e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`.
The returned 3,362,778-byte MSPDI object has SHA-256
`6e0e5321ecadf4b8d9e96685968112803975737a61444104b45ae8cfa522df66`.
Its embedded build and the supplied About Project capture both identify
Microsoft Project `16.0.20228.20186`.

The selected source UID, requested Actual Start, requested Remaining Duration,
blank Actual Finish and zero actual duration/work all reconcile. Project's
derived duration/work changes and zero-span Stop/Resume markers are recorded
separately from the two operator-requested fields. The packaged
`native-run-record.json` was not completed and returned separately; that
provenance omission remains explicit. The returned XML and captures still
independently establish the executing build, saved object, requested edit and
scheduling prompt.

## Fixed-contract result

All 460 common leaf identities remain present. Across 4,140 result-field slots:

- 4,016 are unchanged;
- 43 are exact engine/native agreement;
- 81 belong to nine explicit coded exclusions; and
- zero are unexplained.

The 43 native-changed fields occur across the 12 rows predicted before the run,
including six downstream movements. The first UID 15 run's three unexplained
fields remain recorded and are not retrospectively reclassified; the clean
baseline-exact repeat is the independent result that closes the gate.

## Review corrections included

The closing change also resolves the open review findings on the evidence
branch:

- broader started-work late-date shapes are labelled
  `ACTIVITY_IN_PROGRESS_LATE_DATES_ASSUMED` instead of being published as
  ordinary native-evidenced calculations;
- Stop and Resume now survive MSPDI import and canonical migration;
- the evidence classifier requires an exact scheduled/coded-exclusion
  partition rather than inferring exclusion from a missing engine row;
- unrequested actual duration and assignment actual work fail the controlled
  edit classification; and
- the independent validator rejects a late remaining-start coordinate on a
  completed activity.

## Verification and boundary

The required clean-repeat test passed with the verified external baseline and
returned XML. The whole suite also passed with the verified BOILER, KILN,
CALCINER, untouched-source and clean-repeat files present and both stored-XML
and repeat evidence switches set to fail on absence. Compileall, roadmap render,
roadmap status/gate and whitespace checks passed.

No customer schedule, screenshot, task name or resource name enters git. The
external day-five cohort remains at risk and is still needed to reproduce its
earlier P0/S5 evidence. Broader in-progress shapes remain assumptions until a
separate native experiment measures them.
