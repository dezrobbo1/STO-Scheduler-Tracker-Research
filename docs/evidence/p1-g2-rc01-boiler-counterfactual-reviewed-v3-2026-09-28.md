# RC01 BOILER diagnostic: reviewed V3 measured result

Status: **OUTSIDE NATIVE BOUNDARY; no production correction authorized**.
This is the separate append-only BOILER measurement under the reviewed [V3 pre-result amendment](p1-g2-rc01-boiler-counterfactual-predeclared-v3-2026-09-28.md) and [published V3 tool identity](p1-g2-rc01-boiler-counterfactual-pre-result-identity-v3-2026-09-28.json). The [original V2 result](p1-g2-rc01-boiler-counterfactual-2026-09-28.json) (SHA-256 `30be4ebaac5aa6a6e43aa8d4fa08a90fd531bc506d6b068463a3bbcf4052675e`) remains unchanged. The exact V3 [machine result](p1-g2-rc01-boiler-counterfactual-reviewed-v3-2026-09-28.json) is **25,870 bytes**, SHA-256 `4a7b32e7050b8eb61860d08cc26e544e01e924f4096576ea67009c04c318b248`.

The reviewed tool was published at commit `41dbe02f032085eede56c089ce2602aada6fdeb4`, 26,812 bytes, SHA-256 `a44595d1f7ca4fc78d913737ed4d4a602d3a64ee2771519eb802c0db2aa330bf`. Its exact identity was recorded in the subsequent published commit `de0fe9f5448ffdef8e0291eea30c885efdc0ff51`, **before** this V3 BOILER execution. The tool verifies those values at runtime rather than trusting the most recent tool commit as its own authorization. It also protects existing evidence and transitive production inputs from output aliases and requires a separate output path.

The input was again the same immutable external BOILER source: 3,361,935 bytes, SHA-256 `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`; its hash was unchanged after execution. The tool recalculated the pinned post-RC02 current-root record byte for byte before transforming it. Raw MSPDI inspection confirmed **20 of 20** root assignments had an explicit `Delay=0` and `LevelingDelay=0`; those source values are now enforced before placement and recorded per assignment in the V3 applicability audit. A missing, nonzero or duplicate value fails closed.

| Current family | Production before | V3 diagnostic after | Closed | Worsened/new |
|---|---:|---:|---:|---:|
| RC01 | 144 | 0 | 144 | 0 |
| RC03 | 3 | 3 | 0 | 0 |
| Total | 147 slots across 39 leaves | 3 slots across 2 leaves | 144 | 0 |

The exact 147 before and three after keys and all movement counters match the V2 measured result, including the RC03 residue `L0407/free_float`, `L0407/total_float`, `L0411/total_float`; diagnostic validator violations remain zero. The result fingerprint changes because the registered tool identity changes: V3 is `492fd46892f03abb4e35e61171a3c679f3eb21a25ab3a703baf8743e76ce91c1`. The prior [field/root impact record](p1-g2-rc01-boiler-counterfactual-impact-2026-09-28.json) remains an exact derivation of the unchanged V2 key sets, and these identical V3 sets imply the same totals.

All ten current RC01 roots are eligible for the diagnostic calculation and all ten remain `DIAGNOSTIC_EXTRAPOLATION_REQUIRED`: they are networked and have assignment Work/Units shapes beyond the isolated four-case native V2 matrix. Therefore the **predeclared V3 verdict remains `RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_OUTSIDE_NATIVE_BOUNDARY`**, with `production_rc01_correction_authorized=false`. Neither the complete diagnostic movement nor the clean validator expands the genuine Project native evidence. The next evidence gap is a separately preregistered native test for these networked, differently allocated inputs; RC03 is independently unresolved.

Optional exact-fixture impact retains the earlier V2 measurement: KILN had 133 diagnostically eligible leaves, no V2-native-bounded leaves and unchanged 2,046/2,046 mismatch slots; CALCINER had 946 eligible leaves, no V2-native-bounded leaves and a fail-closed, unmeasured finish-side bound, so **no CALCINER before/after result** was claimed. P1-G2 stays OPEN, P1 stays 4/5 IN PROGRESS and P2 stays NOT STARTED. No production or phase-gate code changed.
