# STO working mode

STO is a shutdown, turnaround and outage scheduler. It imports from a CMMS, from
Primavera P6 or from Microsoft Project; it tracks, manages and schedules
execution in real time; and it exports back to any of them.

Read `docs/goals/ACTIVE.md` for what is being built now, `docs/adr/` for the
decisions that constrain it, `docs/history/` for how those decisions were
reached, and `docs/roadmap/CONSOLIDATION-PLAN.md` for the design behind them.

Rules below marked **(pending)** describe a constraint that becomes enforceable
when the slice that owns it lands. They are written now because they shape what
gets built, but nothing checks them yet — do not assume the machinery exists.

## Do not touch

- **`dezrobbo1/Shutdown-Tracker-Claude` is serving live traffic.** Its API and
  MPXJ worker are running, and `~/shutdown-tracker-deploy/redeploy.sh` builds
  from that working copy. It stays deployed and unmodified until this repository
  passes the parity checklist in `ACTIVE.md`. Read it; do not change it.
- **`dezrobbo1/Shutdown-Tracker` is frozen.** Read its current state through
  `gh api`, not from the local clone, which predates its 2026-08-27 reset.
- `dezrobbo1/PM-Software` continues as independent research and supplies the
  semantic conformance suite. Do not fold it in.

## The boundaries that matter

**STO calculates the schedule.** That is the change of direction from the frozen
repositories, which held Microsoft Project to be the schedule authority and
forbade computing CPM here (ADR-001). Engine claims are bounded by evidence:
the file oracle over real schedules today, and the 50-case conformance suite
once it is copied across **(pending)**. Anything outside those bounds is
labelled, not guessed.

**Imported sources are immutable and every export is a separate candidate.** The
accepted source file is never modified. A candidate is generated beside it, and
what the target system then calculates is a third thing again. This applies to
tooling as well as to services: the command line refuses an output path that
resolves to its input, because some of these schedules have no second copy.

**Three claims are never conflated.** That the approved inputs were written
correctly; that the target system opened the file and produced a result; that a
planner adopted that result. Evidence for one is not evidence for another.

**Every writer is labelled** `baseline`, `diagnostic` or
`native-evidence-derived`, and fails closed outside its proven boundary. A
profile may claim `native-evidence-derived` only when `docs/evidence/` holds an
entry for that target system **and that application build**; writers without one
say `diagnostic` in the interface, not in a footnote. **(pending — the register
and the test that binds profiles to it arrive with the export slice.)**

**Audit is append-only.** Correct and supersede; never rewrite. A record that
was submitted is corrected by a superseding record that cites it.

**The live schedule may change automatically; the exported forecast may not.**
Field progress reaches the live working schedule as soon as it is reported and
is shown as unreviewed. It reaches the approved forecast — what exports and
reports read — only through supervisor and then planner review. **(pending —
arrives with the execution loop.)**

**`sto.core` depends on the standard library only.** Hashing and the canonical
model must be testable without a database or a web framework, and canonical
documents must not pass through a validation library that could reorder or
coerce fields and move a hash. Third-party dependencies belong at the API edge.
Enforced by `tests/test_core_is_stdlib_only.py`.

## Forward-progress test

Before starting substantial work, identify which of these it does:

1. adds a user-visible capability to the current milestone;
2. tests an idea whose result changes the next implementation decision;
3. fixes a defect that blocks, corrupts or materially misrepresents the current
   milestone; or
4. removes complexity that is preventing delivery.

If none applies, defer it. Research, tests, documentation, refactoring,
compatibility work and hardening support those goals; they are not progress by
themselves. A newly discovered issue does not automatically become the next
task: fix it now if it can corrupt source or user data, lose state, create a
false success, or block the milestone; otherwise record it in `ACTIVE.md` and
continue.

Proof-of-concept code may be temporary. Narrow assumptions and hard-coded data
are acceptable while they are understandable and labelled. Do not generalise
experimental code solely because it might be reused.

## Working rules

- One focused outcome per pull request; the smallest coherent change; follow the
  patterns already in the file you are editing.
- **Real customer schedules never enter the repository**, and neither do
  assistant transcripts, which quote them verbatim. Record hashes, counts and
  sanitized structural findings. Keep the files outside and reference them by
  environment variable, as `tests/test_canonical_model.py` does; see
  `fixtures/README.md` for what each file proves and how to recover it.
  `tests/test_docs_carry_no_schedule_content.py` catches the mechanical leaks —
  work-order numbers, routable addresses, credentials — across prose *and* code.
  It does not catch task names; that is a reviewer's job.
- `sto.legacy` is the previous importer and forward-pass engine, kept as the
  oracle the new engine and the MPXJ sidecar are checked against. Do not build
  on it. It is deleted when that cross-check is green on every fixture.
- Schema changes are new versioned files under `infra/migrations/`; never
  rewrite an applied one. **(pending — arrives with persistence.)**
- No history rewriting, force-pushes, or merging without explicit instruction.
- Automated review is advisory. Run one serious pass per meaningful capability
  change and classify each finding fix-now / defer / reject against the current
  milestone. Verify a finding against the code before acting on it: grade has
  not tracked severity well in practice. Do not enter repeated clean-review
  loops, and do not accept a change that buys an unobserved edge case at the
  cost of a new way for a real schedule to stop importing.

## Validation

Python 3.12 or newer. No third-party packages are required to run the suite.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m compileall -q src
git diff --check
```

Six cases exercise real schedules and **skip silently** when they are absent, so
a green run does not by itself mean the file oracle ran. To include them:

```bash
export STO_BOILER_BEFORE=/path/to/boiler-before-no-progress.xml
export STO_BOILER_DAY5=/path/to/day5-candidate.mspdi.xml
```

Manual native verification in Microsoft Project or P6 is required for handoff
milestones and cannot be replaced by a smoke script.
