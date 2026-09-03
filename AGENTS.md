# STO working mode

STO is a shutdown, turnaround and outage scheduler. It imports from a CMMS, from
Primavera P6 or from Microsoft Project; it tracks, manages and schedules
execution in real time; and it exports back to any of them.

Read `docs/goals/ACTIVE.md` for what is being built now and
`docs/goals/roadmap.json` for phases, gate criteria and the rule registry
behind it. `docs/adr/` holds the decisions, `docs/history/` how they were
reached, and `docs/roadmap/CONSOLIDATION-PLAN.md` the design that produced them
— a **frozen record** of 2026-09-02, not a description of the repository today.

## Conventions this file relies on

A backtick around a path means **a path that exists in this repository now**;
`tests/test_governance_references.py` checks every one. A sibling repository
carries its owner prefix. A rule marked **(pending — PR-…)** is registered in
`docs/goals/roadmap.json` and is not enforceable yet: it is written because it
shapes what gets built, and the suite fails when its machinery appears and asks
for it to be promoted. Never write a count of repository contents in prose —
files, tests, cases, rules, ADRs — because that count drifts by construction;
name the thing and let a command count it. A number *measured from a
hash-recorded file* is different: it is evidence, it belongs in an ADR or
`docs/history/`, and it is written with the test that pins it.

## Do not touch

- **`dezrobbo1/Shutdown-Tracker-Claude` is serving live traffic.** Its API and
  MPXJ worker are running, and `~/shutdown-tracker-deploy/redeploy.sh` builds
  from that working copy. It stays deployed and unmodified until this repository
  passes `docs/evidence/PARITY-CHECKLIST.md`. Read it; do not change it.
- **`dezrobbo1/Shutdown-Tracker` is frozen.** Read its current state through
  `gh api`, not from the local clone, which predates its 2026-08-27 reset.
- `dezrobbo1/PM-Software` continues as independent research and supplies the
  semantic conformance suite. Do not fold it in.

## The boundaries that matter

**STO calculates the schedule** (ADR-001, reversing the frozen repositories).
Engine claims are bounded by evidence — the file oracle over real schedules, and
the conformance suite **(pending — PR-conformance-suite)**. Outside those bounds,
label; never guess.

**Imported sources are immutable; every export is a separate candidate.** What
the target system then calculates is a third thing again. This binds tooling too:
the command line refuses an output path resolving to its input, because some of
these schedules have no second copy.

**Three claims are never conflated**: that the approved inputs were written
correctly; that the target system opened the file and produced a result; that a
planner adopted it. Evidence for one is not evidence for another.

**Every writer is labelled** `baseline`, `diagnostic` or
`native-evidence-derived`, and fails closed outside its proven boundary. The
third label requires a `docs/evidence/` entry for that target **and that
application build**, and a writer without one says `diagnostic` in the
interface, not in a footnote. **(pending — PR-evidence-register)**

**Audit is append-only.** Correct and supersede, never rewrite.

**The live schedule may change automatically; the exported forecast may not.**
Reported progress reaches the live schedule at once, marked unreviewed; it
reaches the approved forecast — what exports read — only through supervisor then
planner review. **(pending — PR-approved-forecast)**

**`sto.core` and the research importer `sto.legacy` depend on the standard
library only**, so hashing stays testable without a database, no validation
library can reorder a field and move a hash, and the file oracle never sits
behind the extra the API needs. Third-party code belongs at the API edge.
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
false success, or block the milestone; otherwise record it in `docs/goals/ACTIVE.md` and
continue.

Proof-of-concept code may be temporary. Narrow assumptions and hard-coded data
are acceptable while they are understandable and labelled. Do not generalise
experimental code solely because it might be reused.

## Working rules

- One focused outcome per pull request; the smallest coherent change; follow the
  patterns already in the file you are editing.
- **Real customer schedules never enter the repository**, nor do assistant
  transcripts, which quote them verbatim. Record hashes and sanitized findings;
  keep the files outside and reference them by environment variable.
  `fixtures/README.md` says what each proves and how to recover it.
  `tests/test_docs_carry_no_schedule_content.py` catches the mechanical leaks,
  not task names — those stay a reviewer's job.
- `sto.legacy` is the previous importer and forward-pass engine, kept as the
  oracle the new engine and the MPXJ sidecar are checked against. Do not build
  on it. It is deleted when that cross-check is green on every fixture.
  **(pending — PR-legacy-retirement)**
- Schema changes are new versioned files under `infra/migrations/`; never
  rewrite an applied one. **(pending — PR-migrations)**
- No history rewriting, force-pushes, or merging without explicit instruction.
- Automated review is advisory and bounded by the declared PR outcome and the
  current milestone. One review pass per capability change; classify each
  finding fix-now / defer / reject and verify it against the code first, because
  grade has not tracked severity. A finding blocks merge only when it exposes a
  regression caused by the PR, violates an invariant or acceptance criterion the
  PR claims to establish, can corrupt source or user data, lose state, create a
  false success or security risk, or materially block the current milestone.
  Later-roadmap ownership does not override those blocker categories; if one is
  present it is fix-now even when the complete feature belongs to a later slice.
  Other findings owned by later roadmap slices are deferred, not blockers;
  record a material deferred item once and do not repeatedly reopen it in the
  same PR. Review is complete only when every fix-now finding is resolved, every
  remaining finding is legitimately deferred or rejected, acceptance criteria
  pass and CI is green. No clean-review loops, and never buy an unobserved edge
  case at the cost of a new way for a real schedule to stop importing.
  The reviewer re-runs on every push, so "one pass" is a rule about us, not
  about it: the first pass is answered in full; a later pass is read for the
  blocker categories above and for a guard the repository could carry but does
  not — those are fixed — and everything else it raises is recorded once in a
  single deferral comment and left. A finding the repository's own guards
  could have caught is a finding about the guards: extend the guard, which
  ends that class, rather than fixing the instance.
- **A diagnosis is a claim.** Before writing down why a number is what it is,
  measure the explanation against the data — including by checking that the
  proposed fix would actually change it. Twice now a confident cause has been
  recorded that the evidence did not support.

## Validation

Python 3.12 or newer. No third-party packages are required to run the suite.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m sto.cli roadmap status
python3 -m compileall -q src
git diff --check
```

One class in `tests/test_canonical_model.py` exercises real schedules and
**skips silently** when they are absent, so a green run does not by itself mean
the file oracle ran. Gate criteria rest on it. To include them:

```bash
export STO_BOILER_BEFORE=/path/to/boiler-before-no-progress.xml
export STO_BOILER_DAY5=/path/to/day5-candidate.mspdi.xml
export STO_REQUIRE_BOILER=1     # their absence now fails instead of skipping
```

Cross a phase gate with `STO_REQUIRE_BOILER=1` set. `docs/goals/roadmap.json`
records which criteria depend on evidence that does not always execute, and
`sto roadmap status` and `sto roadmap gate` say so.

Manual native verification in Microsoft Project or P6 is required for handoff
milestones and cannot be replaced by a smoke script.

## Crossing a phase gate

Run `PYTHONPATH=src python3 -m sto.cli roadmap gate` and do what it says. It is
generated from `docs/goals/roadmap.json`, so it cannot disagree with the data.
Between gates this machinery is silent: it speaks only when a reference breaks
or a pending rule's machinery appears.
