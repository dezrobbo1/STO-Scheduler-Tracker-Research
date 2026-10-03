# S7 execution semantics and deterministic recalculation — 2026-10-03

Starting main: `7e70eb41057a68332a41f72ca5df0e33f38c32c8` (PR #67).
P1 remains passed. This is a pure execution-domain operation over an immutable
canonical schedule and a named calculation window. It derives a new document,
hash and full semantic result. It does not publish a `live_working` head or
claim server acceptance, authorisation, event ordering or audit. PL4 will own
those operations and may call this operation after its own acceptance checks.
No schema or migration changed.

## Facts and refusals

- A supported active, automatically scheduled task may acquire an Actual Start
  and a strictly positive Remaining Duration together. The start is then fixed;
  a later positive Remaining Duration changes only the unfinished future.
- It may acquire an Actual Finish at or after its fixed Actual Start. Completion
  sets remaining duration to zero, fixes both actual dates in both passes and
  removes the completed task from current criticality. A start and finish may
  be supplied together. Progress state is read from dates, never percentage.
- Every command names the exact canonical base hash. A different base, changed
  actual history, or a further command on a complete task is refused. Corrections
  that supersede accepted history need their separately audited later path.
- Coded refusals cover missing activity, excluded/inactive/manual/milestone
  activity, `actual_dates` progress policy, elapsed remaining duration, invalid
  or inverted actual times, missing/zero/negative/invalid remaining duration,
  finish without start, nonzero remaining after finish, empty/no-op commands,
  immutable actual history and stale base. The full engine continues to refuse
  unsupported calculation shapes by its existing stable codes.
- The project status date is preserved. `retained_logic`, `progress_override`
  and `none` retain ADR-009 meanings. S7 does not infer a status date, a
  percentage-to-duration conversion or a site-specific status cycle.

## Incremental boundary and equality

`recalculate_network` admits the bounded path only when the immutable previous
pass fingerprints match its network, policies/context/topology stay fixed, the
only changed activity is the named one, and a proper disconnected graph
component contains it. All activities in that component run the *existing*
forward and backward passes. If their merged project finish changes, or the
component is the whole graph, it runs the full reference passes. Other
uncertain shapes also fall back. A changed project finish can change every
component's late bound, so it is never partially reused. Edges cannot cross
the component boundary. Result assembly recalculates full-network float,
criticality, edge disposition/provenance and WBS rollup; these may have global
effects even when pass traversal is bounded. Diagnostic mode/count are outside
canonical schedule and result identity.

The predeclared equality contract compares complete `ForwardPass`,
`BackwardPass`, `FloatAnalysis` and `ScheduleResult` dataclasses. This includes
all activity dispositions, dates, remaining starts, both floats and float
components, criticality, progress state, constraint/deferred reports,
placement/driving lineage, relationship results, assumptions, WBS spans,
provenance and fingerprints. Domain tests also compare the derived canonical
document/hash and results with a fresh full calculation. No computation-mode
metadata participates in semantic equality.

`tests/test_s7_execution.py` generates exactly 1,000 DAGs under deterministic
seeds `0..999` and a candidate-selection seed `seed + 40001`. Each receives two
accepted sequential changes, with fresh full-reference comparison after each.
Networks include varied sizes/shapes, four relationship types, continuous and
gapped calendars, retained logic, progress override and `none`, and changed as
well as unchanged project finish. A candidate the full engine refuses is not
counted as an accepted change: the test checks the incremental path refuses it
with the same code, records that proposal, and tries the next seeded activity.
The completed run yielded 2,000 accepted changes: 1,312 bounded incremental,
688 full fallbacks; 297 changed project finish and 1,703 did not. Four rejected
candidates produced `SCHEDULE_FLOOR_EXCEEDED` on both paths. Sixteen no-op
proposals were skipped before acceptance; each of the 2,000 accepted changes
is asserted to change its activity and network. These counts come from the
post-review rerun under the same network seeds and candidate-selection seeds;
the mode and finish totals coincidentally match the first run. The test pins
all recorded mode, finish, refusal and skipped-no-op counts. Targeted tests
cover immutable actual history, completion, stale bases, exclusions, elapsed
remaining, progress policy, real bounded traversal of a proper component,
whole-network fallback, released edges, deferred constraints and three fresh
processes with different Python hash seeds.

Post-review corrections preserve the prior calculation window, explicit epoch
and resource-calendar application choice in the derived plan and full-reference
oracle. Schedule-derived progress policy, milestone snap, critical-float
threshold, status context and project/window coordinates are checked for drift.
An elapsed planned duration with no prior Remaining Duration now refuses the
creation of Remaining Duration with `EXECUTION_ELAPSED_REMAINING_UNSUPPORTED`;
it cannot silently become non-elapsed. Regression tests cover both settings,
the corresponding fresh full calculations, refusal and unchanged canonical
input/hash.
The bounded review also found that full fallback could drop an explicit
backward-pass project late-finish bound. The backward pass now records whether
that bound was named, even when it equals the old forward finish; fallback
uses the same bound. Default-bound recalculation continues to follow the new
forward finish. Two regressions compare fallback with a fresh full backward
pass for both explicit-bound shapes.

Validation at the local branch before publication:

```text
PYTHONPATH=src python3 -m unittest discover -s tests -p test_s7_execution.py
Ran 16 tests — OK
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 1112 tests — OK (skipped=189)
```

The bare suite's skips include PostgreSQL/API and unavailable private/native
fixtures; this record makes no claim that those ran. PL4 remains responsible
for authenticated acceptance, immutable live version publication, audit,
idempotency, event recovery and subscriber delivery. PL5/PL6/PL7/PL15 are
untouched. P2-G1 is met by the campaign; P2-G2 through P2-G6 remain open.
