# Current engine evidence — 2026-09-10

This is the current-state evidence packet after PRs #44 and #43. The original
measurements are attached to reachable evidence commit `fc30bd34140ad813d7d08655a359d2136f6aa58f`
over correction commit `9ec77db8c984d1b52347eb2906fb3046d3b303c8`. Customer task
names and schedule contents are not recorded here; the real files remain
outside git.

## Evidence levels

- **INTERNAL CONFORMANCE.** The pinned semantic corpus executable by this CPM
  engine is the authority for the stated supported semantics. Its derived case
  census is machine-checked in `docs/goals/roadmap.json`.
- **STORED PROJECT XML AGREEMENT.** The matrix below compares production engine
  output with fields already stored in MSPDI/XML. It does not prove that the
  files were recalculated immediately before export.
- **PROJECT NATIVE RECALCULATION.** Two BOILER files produced by Microsoft
  Project build `16.0.20228.20188` carry four completed-activity observations.
  They show actual dates pinned in both passes, stored total float zero and
  `Critical=false`; the current production rules reproduce that contract.
- **NATIVE ROUND-TRIP.** The task-43 candidate and Project-saved result are a
  bounded single-edit round trip on build `16.0.20228.20188`. This is evidence
  for that transaction only, not general MSPDI writing or full engine parity.
- **ASSUMED / UNMEASURED.** Multi-resource calendar union, successors of
  inactive activities, elapsed lag use of the project calendar, status-date
  behavior on these real schedules, and the remaining stored-field residue are
  not promoted to native evidence.

## Files actually available

| Evidence role | Repository-approved external alias | Bytes | SHA-256 | Stored build |
|---|---|---:|---|---|
| BOILER untouched identity control | STO_BOILER_UNTOUCHED alias: boiler-untouched-source.xml | 3,734,688 | `e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420` | `16.0.20131.20152` |
| BOILER resaved stored-field baseline | STO_BOILER_BEFORE alias: boiler-before-no-progress.xml | 3,361,935 | `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70` | `16.0.20228.20188` |
| BOILER Project-native progress | STO_BOILER_AFTER_NATIVE alias: boiler-after-native-progress.xml | 3,871,501 | `9fabe70debd004aceabe749f3c13abe40823f43746d7db2b15572466c76739c7` | `16.0.20228.20188` |
| BOILER tooling-written round-trip input | external alias: boiler-roundtrip-candidate-task43.xml | 3,264,344 | `7dcd4d828944db9b5284ae1e0b6694571a7ea38433fc20959ed3a130f328cdec` | `16.0.20228.20188` |
| BOILER Project-saved round-trip output | STO_BOILER_ROUNDTRIP_SAVED alias: boiler-roundtrip-project-saved-task43.xml | 3,362,829 | `aff57ce8466d619466c51cb6b0366d25933dc6080d256859a961a1154c4c2dc8` | `16.0.20228.20188` |
| KILN stored-field comparison | STO_KILN alias: kiln-wg047k-source.xml | 3,474,383 | `b7c14b631ecc7c15db7731e4a5159ecefe68aaa1c10e76262f84db6b8c37d3ca` | `16.0.19822.20180` |
| CALCINER stored-field comparison | STO_CALCINER alias: calciner-wg050-source.xml | 14,280,544 | `e952764512ae718e2701c0c79435025b07a5b09124fee4d51b385e92367ed18d` | `16.0.19530.20226` |

The exact day-5 candidate, recorded as 3,747,935 bytes with SHA-256 beginning
`a8d44aa23e20c510`, is **NOT AVAILABLE** in the supplied consolidation archive,
the authorized external fixture directory or the frozen fixture repository. No
synthetic replacement was made and no assertion requiring day-5 is claimed. A live
Windows/Microsoft Project session was also not available to this run.

## Fresh stored-XML agreement matrix

The denominator is the scheduled activity cohort after coded exclusions. The
early columns compare with MSPDI `EarlyStart`/`EarlyFinish`, rather than the
task's potentially different `Start`/`Finish`; early and late pair columns
require both matching fields on the same row. Float and critical columns
compare the production result derived from the production passes, not a
stored-date helper.

| File | Early start | Early finish | Early pair | Late start | Late finish | Late pair | Total float | Free float | Critical | WBS pair |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BOILER | 389/451 | 384/451 | 384/451 | 409/451 | 418/451 | 409/451 | 380/451 | 435/451 | 449/451 | 75/94 |
| KILN | 249/416 | 247/416 | 247/416 | 0/416 | 0/416 | 0/416 | 4/416 | 305/416 | 397/416 | 36/86 |
| CALCINER | 1,647/1,763 | 1,645/1,763 | 1,645/1,763 | 1,572/1,763 | 1,577/1,763 | 1,572/1,763 | 1,488/1,763 | 1,691/1,763 | 1,763/1,763 | 206/219 |

The separate stored-date semantic probe replaces both production pass
coordinate sets with the XML's four stored dates and then calls production
`float_analysis`. It reproduces stored total float on BOILER 449/451, KILN
416/416 and CALCINER 1,763/1,763; it reproduces stored free float on BOILER
448/451, KILN 408/416 and CALCINER 1,732/1,763. The latter two counts changed
from the pre-#44 helper's stale 407 and 1,730 because the probe now executes
the post-#44 bounded lag-inversion rule.

## Dispositions and first mismatches

| File | Scheduled | Coded exclusions | Visible assumptions | Observed first-mismatch structures | Rows after a mismatch |
|---|---:|---|---|---|---:|
| BOILER | 451 | 9 inactive activities; 15 relationships whose endpoint is not scheduled | 11 multi-resource calendar unions; 5 successors of inactive activities; 2 elapsed durations | multi-resource calendar-union spans; successors of inactive activities | 59 |
| KILN | 416 | 11 inactive activities; 1 manually scheduled activity; 20 relationships whose endpoint is not scheduled | 133 multi-resource calendar unions; 14 project-calendar lag assumptions; 6 successors of inactive activities | successors of inactive activities; multi-resource calendar-union span; single-resource long-span stored-field residue | 163 |
| CALCINER | 1,763 | 2 relationships whose endpoint is not scheduled | 956 multi-resource calendar unions; 41 project-calendar lag assumptions; 2 elapsed durations | multi-resource calendar-union spans; task/resource-calendar FS residue; convergence finish milestone; finish-only FF boundary residue | 112 |

The scheduled, exclusion, assumption, and downstream-row counts above are
regression-pinned by the real-file tests. The structural labels are the bounded
analyst classification of those first mismatches; they are qualitative and do
not claim a separately executable class census.

"Rows after a mismatch" is dependency triage only. It does not claim that
changing the first row would make every downstream row agree. The counterfactual
work already recorded in ADR-010 shows that inactive pass-through scheduling
made BOILER worse, while the multi-resource union is an explicit approximation.
The remaining KILN/CALCINER shapes are retained as stored-field residue: an XML
difference alone does not establish which input or Project normalization caused
it, so production was not changed to increase an agreement percentage.

## Current claim boundary

Every activity and relationship in the three matrix files is scheduled,
assumed or excluded with a code. Results keep the following visible when they
apply: several resource calendars approximated by union, inactive-successor
handling, elapsed duration, lag measured on the project calendar, unsupported
or manually scheduled activities, incomplete/secondary constraints and a
status date outside the compiled window. Deferred constraints remain on the
calculation result.

No real file in this packet measures a usable status date: every available
BOILER progress variant declares a date before its own project start. The
status-date policy therefore remains INTERNAL CONFORMANCE, not native evidence.
The UI exposes source and calculated dates but not a relationship UID as a
claimed driver. Binding-driver attribution remains with the later result
explanation slice and does not block the PL14 duration scenario.

The repository command in `docs/goals/ACTIVE.md` supplies the final test and
skip accounting. The focused evidence commands and every available cohort were
green; only assertions requiring the unavailable day-5 file were skipped.
