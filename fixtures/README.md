# Test fixtures and the BOILER file family

Synthetic fixtures live in `tests/fixtures/` and are committed. **Real customer
schedules are not, and never will be** — they are recorded here by hash and
recovery route so the file oracle can be rebuilt on another machine.

## Why this file exists

One class in `tests/test_canonical_model.py` runs against real BOILER schedules
and skips silently when the files are absent. Silence is the failure mode this
document prevents: without it, a checkout where the schedules are missing looks
green while the only tests that exercise a 3.4 MB real-world file are not
running.

Point the tests at the files with:

```bash
export STO_BOILER_BEFORE=/path/to/boiler-before-no-progress.xml
export STO_BOILER_DAY5=/path/to/BOILER-WG110-day5-candidate.mspdi.xml
export STO_BOILER_UNTOUCHED=/path/to/boiler-untouched-source.xml   # the GUID control
export STO_KILN=/path/to/kiln-wg047k-source.xml                    # the float rule
export STO_CALCINER=/path/to/calciner-wg050-source.xml             # the float rule, and the
                                                                   # only declared slack limit
export STO_BOILER_AFTER_NATIVE=/path/to/boiler-after-native-progress.xml
export STO_BOILER_ROUNDTRIP_SAVED=/path/to/boiler-roundtrip-project-saved-task43.xml
export STO_BOILER_CONTROLLED_NATIVE=/path/to/P1-CONTROLLED-NATIVE-PROGRESS-RETURNED.xml
export STO_BOILER_CONTROLLED_NATIVE_REPEAT=/path/to/P1-CONTROLLED-NATIVE-PROGRESS-UID227-RETURNED.xml
PYTHONPATH=src python3 -m unittest discover -s tests
```

The defaults in the test modules point at the original development machine's
copies. Each cohort now runs from the files actually present: BOILER baseline
does not wait for day-5, and KILN, CALCINER and native-completion evidence do
not wait for one another. `STO_REQUIRE_BOILER=1` requires the current stored-XML
matrix (BOILER baseline, KILN and CALCINER). `STO_REQUIRE_NATIVE=1` separately
requires the two Project-recalculated completion files, and
`STO_REQUIRE_CONTROLLED_NATIVE=1` requires the controlled in-progress pair.
`STO_REQUIRE_CONTROLLED_NATIVE_REPEAT=1` requires the baseline and clean UID
227 repeat that closes P1-G3; it does not close the separate P1-G2 static
baseline-reconciliation gate.
`STO_REQUIRE_DAY5=1` requires the exact day-5 candidate. Use only the switch for
the evidence claim being gated.

## The BOILER family: at least four distinct files

They are all "the BOILER schedule" in conversation, and they are **not the same
file**. Any evidence claim must name which one it used.

| SHA-256 (first 16) | File | Bytes | What it is |
|---|---|---|---|
| `e6a3739976580e21` | `boiler-untouched-source.xml` | 3,734,688 | The untouched source cited by **both** `STO` phase-1 calculation evidence and `Shutdown-Tracker`'s native round-trip register. 555 tasks, 472 assignments, `StatusDate 2025-05-09T17:00:00`, no progress, build `16.0.20131.20152` — the same status date and build as the day-5 candidate, which is its progressed successor. What `STO_BOILER_UNTOUCHED` points at — the control for the GUID-stability measurement. Recovered 2026-09-03; see below. |
| `e9b9b7994cc5cc50` | `boiler-before-no-progress.xml` | 3,361,935 | ST-Claude's committed no-progress fixture — a *resave* of the schedule after the unsuccessful three-field write trial, not the untouched source, which is `e6a3…` above. What `STO_BOILER_BEFORE` points at, and what every agreement count in ADR-010 is measured on. |
| `9fabe70debd004ac` | `boiler-after-native-progress.xml` | 3,871,501 | The same schedule after Microsoft Project natively completed task UIDs 43, 318, 319. The genuine Project-recalculation oracle for engine slice S5. |
| `7dcd4d828944db9b` | `boiler-roundtrip-candidate-task43.xml` | 3,264,344 | The generated candidate. Hash matches ST-Claude's evidence record `RT-2026-08-28-BOILER-43` exactly. |
| `aff57ce8466d6194` | `boiler-roundtrip-project-saved-task43.xml` | 3,362,829 | Project's saved result for that candidate. Hash matches the same evidence record exactly. |
| `31443027dedaf411c` | `P1-CONTROLLED-NATIVE-PROGRESS-RETURNED.xml` | 3,362,251 | The resaved baseline after the controlled UID 15 in-progress edit in Microsoft Project build `16.0.20228.20186`. External-only evidence for `P1-NATIVE-PROGRESS-BOILER-UID15-V1`; the supplied filename differed, so identity is by this hash. |
| `6e0e5321ecadf4b8` | `P1-CONTROLLED-NATIVE-PROGRESS-UID227-RETURNED.xml` | 3,362,778 | The clean repeat selected before execution because all nine baseline result fields were exact. Microsoft Project build `16.0.20228.20186` changed the predicted 43 result fields across 12 rows with zero unexplained differences. External-only evidence for `P1-NATIVE-PROGRESS-BOILER-UID227-V1`. |
| `a8d44aa23e20c510` | `BOILER-WG110-day5-candidate.mspdi.xml` | 3,747,935 | 562 tasks, `StatusDate 2025-05-09T17:00:00`, 8 tasks with actuals, 40 calendar exceptions, 635 links, carrying the build label `16.0.20131.20152`. Written by tooling and never recalculated by Project (ADR-009): an oracle for *reported work* — the actual dates and the one in-progress forecast finish, which the pass reproduces exactly — and **not** for late dates, slack, criticality or the status date, which falls sixteen months before its own project start. The separately listed after-native and roundtrip Project-saved files are the completion oracle. |

### The untouched source, recovered

`e6a3739976580e21` is named as the untouched source by `STO`'s own
`results/phase1/*.json` *and* by `Shutdown-Tracker`'s `docs/NATIVE-EVIDENCE.md`
— the single point where two independently produced evidence lines meet. Until
2026-09-03 it was on no machine and in no repository. It was recovered from the
user's Shutdown Tracker source-consolidation package (dated 2026-08-28, folder
`03_ms_project_fixtures` — match on the hash, not the name), where the
package's own `MANIFEST.csv` records the same full SHA-256. The
calculation evidence and the native round-trip evidence can now be compared
against their common baseline.

### Two other real schedules and a native `.mpp`, from the same package

Not BOILER, not previously seen by any test here, and no progress recorded in any
of them. Same policy: outside git, recorded by hash.

| SHA-256 (first 16) | File | Bytes | What it is |
|---|---|---|---|
| `b7c14b631ecc7c15` | `kiln-wg047k-source.xml` | 3,474,383 | KILN work group: 518 tasks, 69 resources, 588 assignments, build `16.0.19822.20180`. A second site's calendar and resourcing conventions. |
| `e952764512ae718e` | `calciner-wg050-source.xml` | 14,280,544 | CALCINER work group: 1,982 tasks, 58 resources, 3,114 assignments, build `16.0.19530.20226`. The largest real schedule available — three and a half times BOILER — and the first real scale test for the engine and the live loop. |
| `14d60d31ae5adf00` | `sample.mpp` | 352,256 | A native `.mpp`. The first on this machine; what the `.mpp` import criterion can be crossed on. |

### One warning
`boiler-before-no-progress.xml` is a *different* file and is not a substitute.

**`BOILER-WG110-day5-candidate.mspdi.xml` has no upstream.** It exists in no
repository, on no branch, in no other copy found on this machine. It is the only
eight-row field-progress cohort; the two controlled Project outputs each carry
one selected in-progress row. Its actual dates and stored forecast finish are a
reported-work oracle. Its status date precedes its project start and its late
dates were not recalculated by Project, so it is not evidence for status-date
scheduling, retained logic, late dates, float or criticality. If it is lost,
that broader field-progress cohort cannot be rerun.

As of 2026-09-03 a second copy sits beside the other four, and every file in
that directory is read-only. Both copies are on one filesystem on one machine,
so this is protection against deletion, not against loss: an off-machine copy is
still owed, and is tracked as `DEP-DAY5-BACKUP` in `docs/goals/roadmap.json`.

## Recovering the four committed fixtures

They are committed in the frozen `Shutdown-Tracker-Claude` repository on
`origin/main` (they are absent from older local checkouts):

```bash
mkdir -p /home/dez/sto-fixtures
cd /home/dez/Shutdown-Tracker-Claude
git fetch origin main
for f in boiler-before-no-progress boiler-after-native-progress \
         boiler-roundtrip-candidate-task43 boiler-roundtrip-project-saved-task43; do
  git show origin/main:fixtures/project-files/boiler/$f.xml > /home/dez/sto-fixtures/$f.xml
done
sha256sum /home/dez/sto-fixtures/*.xml    # compare against the table above
```

## Policy

Real schedules stay outside this repository. Record hashes and sanitized
structural findings; keep the files elsewhere and reference them by environment
variable. `docs/evidence/` holds the native round-trip register, which is keyed
on target system **and application build**.

## Availability checked 2026-09-10

The source-consolidation archive supplied to the closure environment has
SHA-256 `67f4766158c7b76284d8f997cd0345391bb270d4b762510bef59fe4a5ef4c730`.
It contains the untouched BOILER, KILN and CALCINER files above. The four
committed BOILER fixtures were recovered from the frozen repository and match
their recorded hashes. The exact day-5 hash `a8d44aa23e20c510…` is **NOT
AVAILABLE** in either authorized source; it was not reconstructed from task
data. It remains the unique eight-row reported-work cohort, but the controlled
2026-09-20 output now supplies a separate Project-recalculated in-progress row.
The current measurements and complete hashes are in
`docs/evidence/current-engine-evidence-2026-09-10.md`.

## Gate recovery checked 2026-09-20

The same archive was supplied again and matched the recorded full SHA-256, so
its unchanged contents were not treated as a new source. The frozen fixture
repository was read at revision `135218f6f3a6f6fe91ce193d0ee3776ebf0eedbe`;
the four committed BOILER files again matched the sizes and full hashes above.
The exact day-five candidate remains **NOT AVAILABLE** through either recovery
route. See `docs/evidence/p1-gate-entry-decision-2026-09-20.md` for the bounded
native-transition classification and development-entry decision.

## Controlled in-progress run received 2026-09-20

The controlled Project run is evaluated in
`docs/evidence/p1-final-native-progress-2026-09-20.md`. It produced the first
native measurement of late dates for started, unfinished work and led to a
bounded engine correction. Under the predeclared comparison contract, 3 of
4,140 field slots remain unexplained, so at that interim point P1 stayed 3/5
and the file did not
close P1-G2 or P1-G3. `STO_REQUIRE_CONTROLLED_NATIVE=1` makes either member of
this exact pair missing or wrong-identity a hard failure.

## Clean controlled repeat received 2026-09-20

The separately predeclared UID 227 repeat is also evaluated in
`docs/evidence/p1-final-native-progress-2026-09-20.md`. All 43 result fields
changed by Project across the predicted 12-row cohort agree exactly with the
independent engine, with zero unexpected transition differences. That result
closes P1-G3 only. P1-G2 remains open because the full-leaf static comparison
contains 422 `BASELINE_MISMATCH` field instances across 105 leaf identities.
P1 is therefore 4/5 and in progress, and P2 is not started. The first run's
three unexplained fields remain recorded; they were not retrospectively
reclassified.
`STO_REQUIRE_CONTROLLED_NATIVE_REPEAT=1` makes the verified baseline/repeat pair
missing or wrong-identity a hard failure.
