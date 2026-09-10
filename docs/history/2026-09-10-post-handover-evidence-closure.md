# 2026-09-10 — Post-handover engine evidence closure

PR #44 merged before #43 and their combined tree was still `d386628f` when
this closure began. Final automated reviews exposed bounded correctness,
lineage and display blockers; those are isolated in correction PR #45. This
entry records the evidence work stacked after that correction, without
rewriting the historical measurements that earlier revisions produced.

## The stale measurement

The real-file free-float helper still reproduced the pre-C2
shift-then-measure algorithm. Production had moved to bounded lag inversion in
#44, so a green helper no longer meant the test exercised production semantics.
The probe now replaces the forward and backward coordinates with the four
dates stored in XML and calls production `float_analysis`. BOILER remains
448/451; KILN is 408/416 and CALCINER 1,732/1,763 under the current rule.

Every real cohort had also been guarded by unrelated fixture availability in
at least one module. BOILER baseline, KILN, CALCINER, Project-native completion
and day-5 now gate independently. This mattered in the closure environment:
the first seven files named in the current evidence packet were recovered and
hash-verified, while the exact day-5 file was not in any authorized source.
The day-5 canonical, progress, disposition, validation and persistence cohorts
remain conditional and say why; every other available cohort runs. Skip totals
also include separately conditional database and PM-clone suites, so this
record does not assign a fixed assertion count to the missing file.

## What was measured

`docs/evidence/current-engine-evidence-2026-09-10.md` carries exact hashes,
field-by-field early/late/float/criticality agreement, WBS agreement,
disposition counts and sanitized first-mismatch classes for BOILER, KILN and
CALCINER. Those are comparisons with stored Project XML. The completion rule
has a separate four-row Microsoft Project native recalculation oracle, and the
task-43 edit has a separate bounded native round trip. Neither is described as
general Project compatibility.

The twenty first mismatches remain bounded evidence residue: multi-resource
calendar union and inactive-successor assumptions are already visible in the
result, while five KILN/CALCINER shapes lack a native causal oracle. No engine
code was changed to improve a percentage. Rows with a mismatching predecessor
remain dependency triage rather than a claim that fixing one row fixes every
row below it.

## Migration evidence added

A PostgreSQL-required test now constructs an installation through V002, writes
a project, source, immutable version, head and persisted calculation through
the application, applies V003 with the supported migration script, runs schema
drift, reconstructs the workspace and proves both old reads and new writes.
It also proves that V003 rejects reassignment of a calculation to another
version. This is an upgrade test, not a fresh-database substitute.
