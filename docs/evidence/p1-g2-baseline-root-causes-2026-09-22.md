# P1-G2 baseline mismatch root-cause classification — 2026-09-22

This is a diagnosis record, not a scheduler correction. It studies the fixed
P1-G2 matrix produced by the clean UID 227 controlled repeat and leaves every
production formula, importer rule, model, API, UI and gate unchanged.

## Evidence identity and reproduction

Repository basis: `0805bcb44f5122e9499e1dc2449dc25ee6b01abd`.

That commit is a declared **production-code basis**, not an unchecked label.
The diagnostic refuses to run when `src/sto/core`, `src/sto/legacy` or the
controlled-transition classifier differs from that commit, including relevant
uncommitted or untracked files. Before importing repository calculation code it
also redirects Python bytecode lookup to a fresh private cache domain and disables
cache writes, so ignored `__pycache__` entries and caller-supplied
`PYTHONPYCACHEPREFIX` contents cannot replace the verified checkout source.
The cache isolation is exercised by poisoned timestamp/size-valid bytecode
regressions for both the checkout `__pycache__` location and an external
`PYTHONPYCACHEPREFIX`.
Evidence-tool and documentation changes remain independent of that production
boundary. The JSON records the verified path-tree
digest and the evidence tool's own schema, path, byte size and SHA-256. The
pinned path-tree digest is the verification authority when a shallow CI checkout
does not contain the declared commit object.

| Role | Bytes | SHA-256 |
|---|---:|---|
| BOILER baseline | 3,361,935 | `e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70` |
| Clean UID 227 Project repeat | 3,362,778 | `6e0e5321ecadf4b8d9e96685968112803975737a61444104b45ae8cfa522df66` |

The repeat identifies Microsoft Project build `16.0.20228.20186`. The exact
pair reproduces all 460 common leaf identities and the existing complete
nine-field comparison:

| Disposition | Field slots |
|---|---:|
| `UNCHANGED` | 3,594 |
| `BASELINE_MISMATCH` | 422 |
| `ENGINE_NATIVE_AGREEMENT` | 43 |
| `EXPLICIT_EXCLUSION` | 81 |

There are zero unexpected controlled-transition differences. P1-G3 is not
affected by this diagnosis.

The 422 baseline slots occur on 105 source leaf identities with this exact
distribution:

| Field | Slots |
|---|---:|
| Start | 62 |
| Finish | 67 |
| Early Start | 62 |
| Early Finish | 67 |
| Late Start | 42 |
| Late Finish | 33 |
| Total Float | 71 |
| Free Float | 16 |
| Critical | 2 |

The complete sanitized slot inventory is in
`p1-g2-baseline-root-causes-2026-09-22.json`. Per-record leaf pseudonyms replace
source identifiers; absolute source/STO coordinates are omitted; durations and
lags are recorded only as coarse classes. The register retains mismatch deltas,
driver provenance and scheduling shape without task names or notes.

## Diagnostic method

The tool `scripts/evidence/p1_g2_baseline_diagnostics.py` hash-verifies both
external inputs, retains those verified bytes for parsing, and invokes the
production importer, migration, plan builder, forward pass, backward pass and
float analysis.
It also refuses an output path that resolves to, symlinks to or hard-links either
immutable source fixture.

It then distinguishes first divergences from consequences without changing a
production rule:

1. For a forward mismatch, Project's stored predecessor coordinates are fed to
   the existing forward bound, placement and driver primitives. A row that then
   agrees is propagated through that replay driver. A row that still differs is
   a first forward divergence.
2. For a late mismatch, the same procedure is run in reverse with Project's
   stored successor late coordinates and the production backward primitives.
3. For float, production float analysis is rerun with all four Project-stored
   early/late coordinates. A residual there is a first float divergence. A
   mismatch that closes is traced only through the coordinates and relationship
   bounds selected by the actual/source replay calculation.
4. Start/Finish duplicate their corresponding early-coordinate provenance.
   Criticality inherits the Total Float family's causal confidence.

The free-float driver replay uses production's complete zero-span movement-limit
condition. A snapped, incomplete and unpinned zero span stops at the latest valid
working start at or before the horizon; unsnapped, complete and exactly pinned
zero spans retain the horizon. This is replay fidelity, not a scheduler change.

This is a diagnostic counterfactual over stored coordinates. It does not alter
the schedule, substitute a different BOILER file or claim that Project is STO's
architecture authority.

## Root-cause register

Each entry separates three different statements:

1. **Mechanical family** — deterministic slot membership, first-divergence rows,
   dependent rows and actual replay paths.
2. **Causal confidence** — `PROVEN` only when the mismatch origin itself is
   demonstrated; `STRONG_CANDIDATE` when shape and replay identify the leading
   attribution but no causal counterfactual has established it.
3. **Replacement semantics** — whether a justified production rule is known.
   It remains `NOT_ESTABLISHED` for every group.

| Group | Status | Semantic | Root leaves | Propagated-only leaves | Slots |
|---|---|---|---:|---:|---:|
| `G2-RC01` | STRONG_CANDIDATE | Multi-resource calendar-union approximation | 10 | 30 | 160 |
| `G2-RC02` | STRONG_CANDIDATE | Inactive-activity logic boundary | 5 | 61 | 258 |
| `G2-RC03` | PROVEN | Elapsed-duration float basis | 2 | 0 | 3 |
| `G2-RC04` | STRONG_CANDIDATE | One compound multi-resource/inactive Total Float slot | 1 | 0 | 1 |
| **Total** |  |  |  |  | **422** |

Leaf counts are per group and therefore may overlap; the field slots form an
exact disjoint partition. There are 3 `PROVEN` slots, 419
`STRONG_CANDIDATE` slots and zero `UNKNOWN` slots.

### G2-RC01 — multi-resource calendar-union approximation

This family contains ten first-divergence leaves, identified only by the
per-record pseudonyms in the machine-readable register.

For every one, the source task span equals the envelope of its stored assignment
spans. STO deliberately substitutes the union of several resource calendars
and already labels the activity `ACTIVITY_RESOURCE_CALENDARS_UNITED`. Supplying
the source dependency coordinates closes every row classified as dependent
from these first divergences.

The 160 slots are:

| Field | Slots |
|---|---:|
| Start | 24 |
| Finish | 30 |
| Early Start | 24 |
| Early Finish | 30 |
| Late Start | 15 |
| Late Finish | 6 |
| Total Float | 22 |
| Free Float | 7 |
| Critical | 2 |

This is the strongest current causal candidate for the mechanically isolated
family, but the label, assignment-envelope correlation and dependency replay do
not demonstrate that applying an assignment-driven rule removes each first
divergence. It is therefore not `PROVEN`. The family is an existing, visible
assumption outside the claimed supported P1 envelope; replacement requires an
independent assignment-driven contract, not a date-equality patch.

### G2-RC02 — inactive-activity logic boundary

This family contains five first-divergence leaves, identified only by the
per-record pseudonyms in the machine-readable register.

The plan excludes inactive activities and every relationship that loses an
endpoint. Active successors are explicitly labelled
`ACTIVITY_SUCCESSOR_OF_INACTIVE` and scheduled as if the removed incoming edge
did not exist. Project's stored active-row dates retain effects on both sides of
the inactive row: the forward first divergences are active successors, while the
late/free first divergences are active predecessors whose outgoing endpoint was
removed. Source dependency replay closes every dependent date slot; source-date
float replay isolates the two predecessor Free Float first divergences.

The 258 slots are:

| Field | Slots |
|---|---:|
| Start | 38 |
| Finish | 37 |
| Early Start | 38 |
| Early Finish | 37 |
| Late Start | 27 |
| Late Finish | 27 |
| Total Float | 46 |
| Free Float | 8 |

This is the strongest current causal candidate for the mechanically isolated
family. Adjacency and replay do not prove the inactive semantic itself caused
each first divergence. The recorded zero-duration pass-through experiment made
BOILER worse, and the existing files do not expose one consistent inactive-task
rule. A native causal experiment is required to prove or reject the candidate;
a production correction now would be speculation.

### G2-RC03 — elapsed-duration float basis

The two first-divergence leaves are already labelled
`ACTIVITY_DURATION_ELAPSED`. With Project's own dates supplied during the
external run, the ordinary working-time float rule still misses their stored
Total Float; on both rows the stored value equals the elapsed start and finish
coordinate gaps. Their stored Free Float also equals the minimum elapsed
relationship-coordinate gap; this leaves one direct Free Float residual under
the current working-time rule.

This accounts for two Total Float slots and one Free Float slot and remains
`PROVEN`: with identical stored coordinates, elapsed subtraction reproduces the
source values while production working-time arithmetic produces the residual.
That direct arithmetic demonstrates the origin, but does not settle how an
elapsed flag should be carried through STO's pass and fingerprint contracts.

### G2-RC04 — compound Total Float

One Total Float slot consumes an early-coordinate family assigned to `G2-RC02`
and a late-coordinate family assigned to `G2-RC01`. It is kept as a separate
one-slot reconciliation group so neither parent receives false exclusive
credit. Its confidence cannot exceed those two candidate parents, so it is
`STRONG_CANDIDATE`, not independently `PROVEN`, and it is not a fourth
production fix.

## Mechanical graph inventory

The 105 leaves form eleven components when connected only through the engine's
selected forward or late driver relationships:

| Component | Leaves | Slots |
|---|---:|---:|
| G2-C01 | 48 | 227 |
| G2-C02 | 24 | 72 |
| G2-C03 | 13 | 41 |
| G2-C04 | 7 | 29 |
| G2-C05 | 4 | 20 |
| G2-C06 | 3 | 15 |
| G2-C07 | 2 | 5 |
| G2-C08 | 1 | 2 |
| G2-C09 | 1 | 2 |
| G2-C10 | 1 | 3 |
| G2-C11 | 1 | 6 |

Component membership is a mechanical grouping, not a claim that each component
is a separate defect. Source-coordinate replay collapses them into the three
families above; only the elapsed-float family's origin currently meets the
`PROVEN` standard.

## Next root-cause decision

**No production root-cause fix is justified yet.**

The best next target remains `G2-RC02`, because it owns 258 slots across 66
affected leaves, but its causal attribution and replacement semantics are not
established. The required next experiment is a minimal Microsoft Project native matrix for an
active-to-inactive-to-active zero-lag FS chain, covering both forward placement
and predecessor late/free-float influence. It must produce one rule that
predicts both sides of the inactive row, prove or reject the candidate semantic,
and must not reuse the rejected zero-duration pass-through guess.

Therefore no numerical mismatch reduction is promised yet. If that experiment
establishes a rule, the subsequent PR should make only that one semantic
correction and rerun this exact 422-slot inventory plus the real-file forward,
backward and conformance cohorts.

## Gate consequence

Classification is not closure:

- P1-G1 — PASS
- P1-G2 — OPEN
- P1-G3 — PASS
- P1-G4 — PASS
- P1-G5 — PASS

P1 remains **4/5, IN PROGRESS**. P2 remains **NOT STARTED**.
