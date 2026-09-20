# STO working mode

STO is a shutdown, turnaround and outage scheduler being built to import from
a CMMS, from Primavera P6 or from Microsoft Project; to track, manage and
schedule execution in real time; and to export back to any of them. Today it
does two of those separately: it imports Microsoft Project XML into a canonical
model and stores it with a durable identity, and it has its own CPM engine over
that model. Connecting the two — a stored schedule calculated and shown — is
`PL13`, and `docs/goals/ACTIVE.md` says what is built and what is next.

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
- **`dezrobbo1/Shutdown-Tracker` is frozen.** Read it through `gh api`; there
  is no local clone any more, and the one there was predated its 2026-08-27
  reset.
- `dezrobbo1/PM-Software` continues as independent proof-of-concept research.
  Its semantic conformance corpus is copied into `src/sto/conformance/` at the
  commit `src/sto/conformance/MANIFEST.json` names, every file pinned by
  SHA-256; the copy is moved only by `scripts/conformance/pin-corpus.py`, never
  by editing a case. The rest of that repository is not folded in.

## The boundaries that matter

**STO calculates the schedule** (ADR-001, reversing the frozen repositories).
Engine claims are bounded by evidence — the file oracle over real schedules, and
the pinned conformance corpus (PR-conformance-suite). Outside those bounds,
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

**Communication is descriptive context, not execution authority.** Messages,
replies, reactions, photos and annotations cannot mutate execution or schedule
state, and communication/media/delivery/notification state stays outside
schedule hashes. An execution action offered from a message is a separate,
explicit, authorised and audited command, validated by the execution domain.
ADR-016 records the boundary. **(pending — PR-communication-not-authority)**

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
  rewrite an applied one. `infra/migrations/CHECKSUMS` pins each file and
  `tests/test_migrations_are_immutable.py` holds it to that;
  `scripts/db/apply-migrations.sh` refuses a changed file at the database.
- No history rewriting, force-pushes, or merging without explicit instruction.
- Reviewers and implementers follow **Code Review Rules** below. A severity
  badge or unresolved thread is not, by itself, a merge decision.
- **A diagnosis is a claim.** Before writing down why a number is what it is,
  measure the explanation against the data — including by checking that the
  proposed fix would actually change it. Twice now a confident cause has been
  recorded that the evidence did not support.

## Code Review Rules

These rules apply to automated and human PR review. Read the declared outcome,
supported inputs, acceptance criteria and exclusions alongside
`docs/goals/ACTIVE.md`. Scope limits do not waive existing safety invariants or
permit silently dropping previously supported behaviour.

### Material risks first

Raise fix-now findings for concrete security risks, credential or project-data
exposure, source/data corruption, lost state, incorrect scheduling results,
false success, broken immutable lineage or append-only audit, and material
regressions in the supported workflow. Also flag failures of acceptance criteria
or required evidence the PR claims to establish. Inspect affected callers and
boundaries, not just changed lines. Later-roadmap ownership does not excuse
these defects; a rare but credible security or data-integrity failure still
matters.

Test and tooling defects qualify when they invalidate required evidence or
break explicitly supported commands. Do not expand a bounded PR into support
for hypothetical environments, every connection option, or future features.
Style, optional refactoring and speculative hardening without a material
consequence are not blockers. Leave mechanical formatting checks to CI.

### Evidence and proportionate correction

For each finding identify the triggering input or response ordering, the
relevant code path, expected versus actual behaviour, and the material
consequence or claimed contract it violates. Distinguish executed reproduction
from source analysis; a clear code path can establish a risk without a live
exploit or an unavailable private fixture. State uncertainty rather than
inventing evidence. Judge severity from impact, not a badge or a count of tests.

Classify findings **FIX NOW / DEFER / REJECT**. Group instances of the same root
cause and prefer the smallest coherent correction. For a material fix, test the
affected lifecycle or caller boundary, including the supported counter-case,
rather than patching only the latest symptom. **A missing regression test
identifies how to fix a material defect; it does not by itself make a finding a
merge blocker.** Do not demand exhaustive coverage of an unclaimed input space.
Record material deferrals once, with a reason and owning slice.

### Bounded follow-up and closure

Review the complete PR once. On corrective pushes, review the correction,
affected callers and earlier material findings, not a fresh repository-wide
hardening programme. Report a newly demonstrated blocker even on a later pass;
do not repeatedly reopen fixed or legitimately deferred findings without new
material evidence. Do not request repeated clean-review passes solely to obtain
an empty automated report.

The owner may close review when the actual published head meets acceptance,
required CI/evidence checks pass, every fix-now finding is resolved and the rest
are legitimately deferred or rejected. Do not weaken tests, required checks,
security boundaries or phase gates to reach that state. Automated review is
advisory, not proof of correctness; zero comments is not the acceptance criterion.
Merge still requires explicit user instruction.

## Validation

Python 3.12 or newer. No third-party packages are required to run the suite.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m sto.cli roadmap status
python3 -m compileall -q src
git diff --check
```

The tests that exercise real schedules — one class in
`tests/test_canonical_model.py` and the engine's file-oracle modules beside it,
named for the schedules they read — **skip silently** when the files are
absent, so a green run does not by itself mean the file oracle ran. Gate
criteria rest on them. To include them:

```bash
export STO_BOILER_BEFORE=/path/to/boiler-before-no-progress.xml
export STO_KILN=/path/to/kiln-wg047k-source.xml
export STO_CALCINER=/path/to/calciner-wg050-source.xml
export STO_REQUIRE_BOILER=1     # the stored-XML matrix is required
```

Use `STO_REQUIRE_DAY5=1` with `STO_BOILER_DAY5` only when the exact day-5
candidate is available, and `STO_REQUIRE_NATIVE=1` with both native files for
Project-recalculated completion evidence. Use
`STO_REQUIRE_CONTROLLED_NATIVE=1` with `STO_BOILER_CONTROLLED_NATIVE` and
`STO_BOILER_BEFORE` for the controlled in-progress evidence. Cross the
stored-XML evidence gate with `STO_REQUIRE_BOILER=1` set. `docs/goals/roadmap.json`
records which criteria depend on evidence that does not always execute, and
`sto roadmap status` and `sto roadmap gate` say so.

The persistence and API tests need a PostgreSQL and the `api` extra (ADR-005);
in the bare suite they skip. To run them, and to make their absence a failure:

```bash
uv sync --extra api --extra test
STO_REQUIRE_DB=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

They create and drop their own database on the server named by
`STO_TEST_ADMIN_URL` (default: the local loopback instance on 5433).

The conformance corpus needs nothing: it is in the package and every run checks
it against its pins. A test additionally compares the copy with the pinned
commit in a `dezrobbo1/PM-Software` clone named by `STO_PM_SOFTWARE_DIR`, and
skips without one; `STO_REQUIRE_PM=1` makes that absence a failure.

Manual native verification in Microsoft Project or P6 is required for handoff
milestones and cannot be replaced by a smoke script.

## Crossing a phase gate

Run `PYTHONPATH=src python3 -m sto.cli roadmap gate` and do what it says. It is
generated from `docs/goals/roadmap.json`, so it cannot disagree with the data.
Between gates this machinery is silent: it speaks only when a reference breaks
or a pending rule's machinery appears.
