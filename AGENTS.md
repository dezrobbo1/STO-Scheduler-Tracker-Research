# STO working mode

STO is a shutdown, turnaround and outage scheduler. It imports from a CMMS, from
Primavera P6 or from Microsoft Project; it tracks, manages and schedules
execution in real time; and it exports back to any of them.

This repository is the product. `dezrobbo1/Shutdown-Tracker-Claude` and
`dezrobbo1/Shutdown-Tracker` are frozen references whose work is being folded in
here; `dezrobbo1/PM-Software` continues as independent research and supplies the
semantic conformance suite. Read `docs/goals/ACTIVE.md` for what is being built
now and `docs/adr/` for the decisions that constrain it.

## The boundaries that matter

**STO calculates the schedule.** That is the change of direction from the frozen
repositories, which held that Microsoft Project was the schedule authority and
forbade computing CPM here. Every engine claim is bounded by the conformance
suite and by the file oracle; anything outside those bounds is labelled, not
guessed.

**Imported sources are immutable and every export is a separate candidate.** The
accepted source file is never modified. A candidate is generated beside it, and
what the target system then calculates is a third thing again.

**Three claims are never conflated.** That the approved inputs were written
correctly; that the target system opened the file and produced a result; that a
planner adopted that result. Evidence for one is not evidence for another.

**Every writer is labelled.** `baseline`, `diagnostic` or
`native-evidence-derived`, and it fails closed outside its proven boundary. A
profile may only claim `native-evidence-derived` when `docs/evidence/` holds an
entry for that target system and that application build. Writers without one say
`diagnostic` in the interface, not in a footnote.

**Audit is append-only.** Correct and supersede; never rewrite. A record that
was submitted is corrected by a superseding record that cites it.

**The live schedule may change automatically; the exported forecast may not.**
Field progress reaches the live working schedule as soon as it is reported, and
is shown as unreviewed. It reaches the approved forecast — which is what exports
and reports read — only through supervisor and then planner review.

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
false success, or block the milestone; otherwise record it and continue.

Proof-of-concept code may be temporary. Narrow assumptions and hard-coded data
are acceptable while they are understandable and labelled. Do not generalise
experimental code solely because it might be reused.

## Working rules

- One focused outcome per pull request; the smallest coherent change; follow the
  patterns already in the file you are editing.
- Schema changes are new versioned files under `infra/migrations/`. Never
  rewrite an applied migration.
- Real customer schedules never enter the repository. Record hashes and
  sanitized structural findings; keep the files outside and reference them by
  environment variable, as `tests/test_canonical_model.py` does.
- No history rewriting, force-pushes, or merging without explicit instruction.
- Automated review is advisory. Run one serious pass per meaningful capability
  change and classify each finding fix-now / defer / reject against the current
  milestone. Do not enter repeated clean-review loops.

## Validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests   # or: uv run pytest
python3 -m compileall -q src
git diff --check
```

Manual native verification in Microsoft Project or P6 is required for handoff
milestones and cannot be replaced by a smoke script.
