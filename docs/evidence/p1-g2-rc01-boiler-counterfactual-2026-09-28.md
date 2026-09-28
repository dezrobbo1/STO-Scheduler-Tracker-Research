# RC01 BOILER assignment-envelope diagnostic: measured result

Status: **OUTSIDE NATIVE BOUNDARY; production RC01 correction not authorized**.
This is an append-only result of the already published [pre-result contract](p1-g2-rc01-boiler-counterfactual-predeclared-2026-09-28.md) and [pre-result identity V2](p1-g2-rc01-boiler-counterfactual-pre-result-identity-v2-2026-09-28.json). The earlier `NOT RUN` records describe their state before the exact BOILER file arrived; they remain unchanged. The frozen tool at commit `236d8988da0f8cd8ed27407ddc31f39eb04dfb7e` (24,519 bytes; SHA-256 `9b595114c0fe882fec5dae58abba090973a822eea62431834238f1998bc14437`) produced the [machine result](p1-g2-rc01-boiler-counterfactual-2026-09-28.json), 24,210 bytes, SHA-256 `30be4ebaac5aa6a6e43aa8d4fa08a90fd531bc506d6b068463a3bbcf4052675e`. A separate [impact record](p1-g2-rc01-boiler-counterfactual-impact-2026-09-28.json) derives field/root counts and reports the optional fixture scans; it pins the exact machine result. No production scheduler code was changed.

## Identity and calculation

The externally supplied, unmodified BOILER baseline was exactly 3,361,935 bytes, SHA-256 `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`. It remains outside git. Starting current-root evidence was pinned by SHA-256 `9a3ef68637b6e213188400f05fdca9bd216eebfbafa100f10f817623f5b8f3d3`; the tool **recalculated and reproduced that complete record byte for byte before applying the diagnostic**. Native V2 evidence was pinned by SHA-256 `71702adb09f08014c8ce14bed7651162bff65787f8d4d4945bb2383710ca6a6c`. The production/main basis was `60313811d6867c28e71cb22bccfd3cc0c8f1618d`.

The diagnostic temporarily replaced production forward/backward placement only for eligible unprogressed fixed-units tasks. Each assignment's exact `Work / Units` duration was placed on its own resource calendar; the task's early and late spans were the corresponding assignment envelopes. Network bounds, floats, and unaffected placement used the production primitives. Project output dates served only as the comparison oracle. The tool restored the original placement functions and checked the BOILER source bytes again before publishing a separate atomic result. Its candidate projection fingerprint was `a69ad4c4d9fb0327655ba4a22f504591491422a3238d9caed1675f88cc3fecef`.

## Ten-current-root applicability audit

All ten roots were diagnostically eligible, and all ten were labelled `DIAGNOSTIC_EXTRAPOLATION_REQUIRED`. Each is an active, unprogressed, automatic fixed-units task with two assignments on distinct resource calendars, but **each has at least one predecessor and successor**. V2 tested isolated tasks. The BOILER assignments also include 200% units and Work/duration combinations outside V2's exact two 100%, four-hour assignments. The full audit in the machine result records each leaf ID, assignment/resource/calendar UID, Work, Units, task flags and duration, and predecessor/successor type and lag; it contains no customer task names.

| Root leaf | Before RC01 slots | Closed | Current first-divergence slots closed | V2 boundary |
|---|---:|---:|---:|---|
| L0070 | 4 | 4 | 3 | Extrapolation |
| L0075 | 4 | 4 | 3 | Extrapolation |
| L0080 | 6 | 6 | 1 | Extrapolation |
| L0083 | 3 | 3 | 3 | Extrapolation |
| L0084 | 5 | 5 | 3 | Extrapolation |
| L0114 | 5 | 5 | 3 | Extrapolation |
| L0127 | 2 | 2 | 1 | Extrapolation |
| L0148 | 3 | 3 | 1 | Extrapolation |
| L0157 | 1 | 1 | 1 | Extrapolation |
| L0190 | 3 | 3 | 3 | Extrapolation |

The 22 closed first-divergence slots are the **recomputed current** roles in the pinned post-RC02 record, not inherited roles from the historical 422-slot record. Dependent and derived movement is reconciled by the exact before/after key sets.

## Measured movement

| Current family | Before | Diagnostic after | Closed | New |
|---|---:|---:|---:|---:|
| RC01 | 144 | 0 | 144 | 0 |
| RC03 | 3 | 3 | 0 | 0 |
| Total | 147 across 39 leaves | 3 across 2 leaves | 144 | 0 |

The remaining keys are `L0407/free_float`, `L0407/total_float`, `L0411/total_float`, exactly the previously recomputed RC03 residue. The diagnostic closed 144 RC01 slots, left **zero** RC01 slots unchanged or worsened, and created no new slots. No RC03 slot worsened. The diagnostic validator reported zero violations. Per-field totals and the exact 147 before/three after `(leaf_id, field)` keys are in the linked machine records.

Running the full real-fixture suite exposed a stale summary-rollup count in `tests/test_rollup_boiler.py`. On this pinned 3,361,935-byte BOILER source, **current production** (before the diagnostic) yields 94 rolled summaries, one empty summary and **88** exact source spans. The historical fixture expectation of 75 exact spans predated the RC02 production change. The measured count was repinned to 88 without changing the rollup implementation, its triage assertion, its fixture guard or any phase gate. This count belongs to current production; it does not describe the diagnostic candidate.

The predeclared stopping rule classifies this result as `RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_OUTSIDE_NATIVE_BOUNDARY`, despite the complete RC01 movement, because no root satisfies the exact native-tested shape. **No production RC01 correction is authorized**; P1-G2 remains open. The next evidence gap is native Project execution for the networked, differently sized and differently allocated assignment shapes actually found at these ten roots, under a fresh predeclared experiment. Do not extrapolate the four isolated synthetic cases to production scheduling. RC03 remains a distinct unresolved family.

## Other exact fixtures

The exact KILN archive member was 3,474,383 bytes, SHA-256 `b7c14b631ecc7c15db7731e4a5159ecefe68aaa1c10e76262f84db6b8c37d3ca`. Of 416 scheduled leaves, 133 were diagnostically eligible; none was within the exact V2 native boundary. The same diagnostic calculated 2,046 mismatch slots before and after, with zero closed, new, improved, or worsened slots and zero diagnostic validator violations. This is an impact check, not a native or production validation of those shapes.

The exact CALCINER archive member was 14,280,544 bytes, SHA-256 `e952764512ae718e2701c0c79435025b07a5b09124fee4d51b385e92367ed18d`. Of 1,763 scheduled leaves, 946 were diagnostically eligible; none was within the V2 native boundary. The candidate refused a finish-side lower bound because moving independent assignments to satisfy that bound has no measured rule. **CALCINER before/after agreement, new/worsened keys, and validator outcome were not calculated**; this is a fail-closed impact, not a pass. These optional fixtures did not tune the BOILER result.

P1-G1/G3/G4/G5 remain PASS; P1-G2 remains OPEN; P1 is 4/5 IN PROGRESS; P2 is NOT STARTED. Neither a production RC01 fix nor RC03 belongs to this diagnostic PR.
