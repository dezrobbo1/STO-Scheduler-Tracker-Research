# RC01 BOILER assignment-envelope diagnostic: pre-result contract

Status: **NOT RUN — EXACT BOILER BASELINE REQUIRED**. This record commits the
calculation, strict applicability boundary and stopping rule before any real
BOILER result is seen. It changes no production scheduling code or phase gate.
The pre-result commit SHA and tool size/hash are recorded in the PR at commit
publication; a future result must repeat them from the committed tool. The
companion JSON fixes input identities and the decision rule.

The required external BOILER XML is **3,361,935 bytes**, SHA-256
`e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70`.
The source-consolidation archive contains another BOILER XML of 3,734,688
bytes, SHA-256 `e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420`;
it is **not** this experiment's BOILER input. No KILN/CALCINER result is
claimed. The canonical V2 synthetic fixture is not a BOILER substitute.

## Native and production provenance

Current post-RC02 evidence JSON SHA-256:
`9a3ef68637b6e213188400f05fdca9bd216eebfbafa100f10f817623f5b8f3d3`.
It records 147 slots across 39 leaves, with 144 RC01 and 3 RC03. The current
RC01 root set is fixed in the tool; production replay must regenerate the
entire existing evidence document byte-for-byte before the transform executes.
The exact 147 `(leaf_id, field)` keys are read from that pinned record.

V2 native valid-return evidence JSON SHA-256:
`71702adb09f08014c8ce14bed7651162bff65787f8d4d4945bb2383710ca6a6c`.
The 54,152-byte valid Project save has SHA-256
`674b2a70649991ac6b9624ced1d16ca88a5287fed35da08486a59986360d513e`,
build `16.0.20326.20140`, and passed all seven preregistered predicates. This
is native evidence for that synthetic four-case matrix, not for every BOILER
task or dependency configuration.

## Calculation and eligibility

The diagnostic temporarily wraps only production `_place` in the forward and
backward passes, restoring the original functions on every exit. Production
network bounds, relationship logic, progress logic, measuring calendars,
float and criticality remain in use. Each eligible unprogressed fixed-units
activity with at least two assignments on distinct resource calendars gets a
per-assignment duration of **integer seconds** `Work * 1000 / Units_permille`.
Each assignment is placed on its own compiled resource calendar. The task
Start/Finish (and late Start/Finish) are the minimum assignment start and
maximum assignment finish. The forward calculation refuses a finish-side
lower bound not satisfied by that envelope; it does not invent a rule for
moving one assignment independently. Hard constraints, progressed tasks,
explicit task calendars, ignore-resource-calendar tasks, unresolved resources,
zero/fractional Work/Units and any other unsupported shape are not transformed.

For each of the ten current BOILER RC01 roots the eventual audit records task
kind, flags, duration/type, Work/Units, calendar identities, predecessors,
successors, lags and assumptions. `WITHIN_V2_COUNTERFACTUAL_BOUNDARY` is
reserved for exact synthetic-tested shapes; even a calculable networked root
is `DIAGNOSTIC_EXTRAPOLATION_REQUIRED` because V2 did not test dependencies.
The single-resource control stays under production placement. A BOILER result
with any root outside that native boundary cannot authorize a production fix.

Project-stored task/assignment Start, Finish, early/late dates, float and
criticality are used only for **comparison**. Synthetic tests change those
observations without changing the diagnostic calculation. The wrapper's
result is labelled `sto-diagnostic-p1-g2-rc01-assignment-envelope-v1` and
cannot be published as a production result. Validation uses the production
validator for every unchanged rule and separately checks the exact early and
late per-assignment envelopes where the production validator's single-span
length rule is inapplicable.

## Decision and publication

`SUPPORTED` requires exact starting inventory and projection, all ten roots
accounted for and within the V2 native boundary, a clean diagnostic validator,
all 144 RC01 slots closed, exactly the independently justified RC03 residue,
no new/worsened keys, no lost eligible leaf and immutable BOILER bytes.
`PARTIAL`, `REJECTED`, `OUTSIDE_NATIVE_BOUNDARY` and no-result conditions are
fixed in the machine-readable contract. No outcome is preferred. A supported
diagnostic could authorize only a **later separate production PR**. It cannot
close P1-G2. The tool refuses direct, normalized, symlink and hard-link
output aliases and atomically publishes a separate evidence candidate.

The exact baseline has not been supplied in this environment. Root-level
applicability, before/after BOILER slots, KILN/CALCINER impacts and a BOILER
classification are **NOT RUN**, not inferred from the synthetic controls.
