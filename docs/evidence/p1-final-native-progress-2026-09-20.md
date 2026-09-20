# P1 controlled native progress evidence — 2026-09-20

This record evaluates `P1-NATIVE-PROGRESS-BOILER-UID15-V1`. It contains no
customer task names or schedule content. The source and returned schedules
remain outside git.

## Verified objects and execution

| Object | Bytes | SHA-256 |
|---|---:|---|
| BOILER baseline | 3,361,935 | `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70` |
| Project-saved controlled output | 3,362,251 | `31443027dedaf411c5c33b03806881c370f7f039ca520569a1fa0fa59f0b5278` |

The output identifies Microsoft Project `16.0.20228.20186` as its writer. The
executing build is independently visible in the supplied About Project capture.
The supplied filename was `P1-CONTROLLED-NATIVE-PROGRESS-WORKING(1).xml`, not
the requested returned filename; the full MSPDI object, its writer, identity
and contents were evaluated rather than inferring execution from its name.

The only operator-requested update was source UID 15:

- Actual Start: unset to `2026-09-08T07:30:00`;
- Remaining Duration: 7,200 seconds to 3,600 seconds;
- Actual Finish remained unset.

Project normalized planned Duration from 7,200 to 3,600 seconds, task Work from
14,400 to 7,200 seconds and the single 200% assignment's work from 14,400 to
7,200 seconds. All reconcile exactly with zero actual duration/work and the
requested remaining duration. A Planning
Wizard warning reported that one derived task moved before Project Start;
`Continue` was selected. Project Start and the other project scheduling settings
remain unchanged in the returned XML.

## Measured correction

The native file supplies the first Project-recalculated late dates for an
activity that has started and not finished. It demonstrates that Project:

1. keeps the activity's reported `LateStart` on its immutable Actual Start;
2. places its remaining duration separately at the latest feasible span;
3. uses the Actual Start boundary for already-satisfied incoming logic; and
4. propagates that boundary backward through the in-sequence predecessor chain.

STO previously exposed the late remaining-span start as `LateStart`. The bounded
correction keeps an internal late remaining start for duration and float while
reporting the Actual Start as `LateStart`. Out-of-sequence retained logic keeps
using the late remaining boundary. The independent validator consumes both
coordinates and the affected pass profiles are versioned.

The correction changes STO's controlled result on 31 rows: the edited row, six
downstream rows and the in-sequence predecessor cohort. All 31 remain scheduled;
the complete leaf accounting remains 433 supported/calculated, 18
assumed/labelled and 9 excluded/coded across 460 leaves.

## Complete comparison

The predeclared nine-field contract covers all 460 common leaf identities and
4,140 field slots. No activity identity or relationship was added or removed.

| Classification | Field slots |
|---|---:|
| `UNCHANGED` | 3,928 |
| `ENGINE_NATIVE_AGREEMENT` | 128 |
| `EXPLICIT_EXCLUSION` | 81 |
| `UNEXPLAINED` | 3 |

The 131 native-changed field instances occur across 31 rows. The expected input
classification is two `DIRECT_CONTROLLED_EDIT` fields and three
`PROJECT_DERIVED_PROGRESS_INPUT` normalizations.

The remaining three fields are `LateStart`, `LateFinish` and `Total Float` on
one upstream source identity. Corrected STO and Project converge on the native
values, but STO did not agree with that row's baseline values because another
successor branch already carries a pre-existing stored-late-date mismatch. The
contract fixed before the native output existed permits engine agreement only
where that baseline field was already exact. The three values therefore remain
`UNEXPLAINED`; convergence after seeing the answer is not reclassified as a
pass.

The earlier intake warning about assignment inputs was a verifier defect:
assignment Start and Finish are recalculated schedule outputs. Seven assignment
spans move, including the selected assignment, while non-selected assignment
identity, linkage, units, work and progress stay unchanged. The corrected guard
continues to fail on changes to those inputs.

## Gate decision

| Criterion | Status |
|---|---|
| P1-G1 | PASS |
| P1-G2 | OPEN — three controlled native fields remain unexplained |
| P1-G3 | OPEN — unexpected differences are not zero |
| P1-G4 | PASS |
| P1-G5 | PASS |

P1 remains **3/5 and in progress**. No Phase 2 slice starts and the earlier
limited-development exception is not used.

The executable evidence is `tests/test_controlled_native_progress_boiler.py`.
Set `STO_BOILER_BEFORE`, `STO_BOILER_CONTROLLED_NATIVE` and
`STO_REQUIRE_CONTROLLED_NATIVE=1` so either missing or wrong-identity external
file fails instead of skipping.

The smallest next experiment uses source UID 227 from the same verified
baseline. It is a supported, unstarted, auto-scheduled leaf with one ordinary
zero-lag FS predecessor, two ordinary zero-lag FS successors, one assignment,
no constraint, no elapsed duration and exact baseline agreement across all nine
fields. Actual Start `2026-09-14T11:00:00` plus Remaining Duration 14,400 seconds
(from 28,800) makes STO change 12 supported baseline-exact rows and move six
downstream activities. That repeat avoids the pre-existing inexact branch that
prevents this experiment from closing the gate.
