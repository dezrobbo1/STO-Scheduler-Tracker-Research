# Test fixtures and the BOILER file family

Synthetic fixtures live in `tests/fixtures/` and are committed. **Real customer
schedules are not, and never will be** — they are recorded here by hash and
recovery route so the file oracle can be rebuilt on another machine.

## Why this file exists

Six cases in `tests/test_canonical_model.py` run against real BOILER schedules
and skip silently when the files are absent. Silence is the failure mode this
document prevents: without it, a checkout where the schedules are missing looks
green while the only tests that exercise a 3.4 MB real-world file are not
running.

Point the tests at the files with:

```bash
export STO_BOILER_BEFORE=/path/to/boiler-before-no-progress.xml
export STO_BOILER_DAY5=/path/to/BOILER-WG110-day5-candidate.mspdi.xml
export STO_BOILER_UNTOUCHED=/path/to/boiler-untouched-source.xml   # the GUID control
PYTHONPATH=src python3 -m unittest discover -s tests
```

The defaults in the test module point at this machine's copies.

## The BOILER family: at least four distinct files

They are all "the BOILER schedule" in conversation, and they are **not the same
file**. Any evidence claim must name which one it used.

| SHA-256 (first 16) | File | Bytes | What it is |
|---|---|---|---|
| `e6a3739976580e21` | `boiler-untouched-source.xml` | 3,734,688 | The untouched source cited by **both** `STO` phase-1 calculation evidence and `Shutdown-Tracker`'s native round-trip register. Same status date and build as the day-5 candidate, which is its progressed successor; no progress. What `STO_BOILER_UNTOUCHED` points at — the control for the GUID-stability measurement. Recovered 2026-09-03; see below. |
| `e9b9b7994cc5cc50` | `boiler-before-no-progress.xml` | 3,361,935 | ST-Claude's committed no-progress fixture. What `STO_BOILER_BEFORE` points at. |
| `9fabe70debd004ac` | `boiler-after-native-progress.xml` | 3,871,501 | The same schedule after Microsoft Project natively completed task UIDs 43, 318, 319. The genuine Project-recalculation oracle for engine slice S5. |
| `7dcd4d828944db9b` | `boiler-roundtrip-candidate-task43.xml` | 3,264,344 | The generated candidate. Hash matches ST-Claude's evidence record `RT-2026-08-28-BOILER-43` exactly. |
| `aff57ce8466d6194` | `boiler-roundtrip-project-saved-task43.xml` | 3,362,829 | Project's saved result for that candidate. Hash matches the same evidence record exactly. |
| `a8d44aa23e20c510` | `BOILER-WG110-day5-candidate.mspdi.xml` | 3,747,935 | 562 tasks, `StatusDate 2025-05-09T17:00:00`, 8 tasks with actuals, 40 calendar exceptions, 635 links, written by Project build `16.0.20131.20152`. The only progress oracle. |

### The untouched source, recovered

`e6a3739976580e21` is named as the untouched source by `STO`'s own
`results/phase1/*.json` *and* by `Shutdown-Tracker`'s `docs/NATIVE-EVIDENCE.md`
— the single point where two independently produced evidence lines meet. Until
2026-09-03 it was on no machine and in no repository. It was recovered from the
user's Shutdown Tracker source-consolidation package (dated 2026-08-28, folder
`03_ms_project_fixtures`), whose own manifest records the same full SHA-256.
The calculation evidence and the native round-trip evidence can now be compared
against their common baseline. Recovery route if lost again: that package, or
ask for the original extract by hash.

### One warning
`boiler-before-no-progress.xml` is a *different* file and is not a substitute.

**`BOILER-WG110-day5-candidate.mspdi.xml` has no upstream.** It exists in no
repository, on no branch, in no other copy found on this machine. It is the only
file carrying a status date and reported actuals, which makes it the only oracle
for status-date scheduling, retained logic and progress override. If it is lost,
engine slice S5 loses its verification and there is nothing to restore from.
Back it up somewhere durable.

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
