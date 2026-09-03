# 2026-09-03 — Reviewing the frozen plan against what is actually here

The consolidation plan was reviewed against this repository, the sibling
repositories and this machine. The question was two-sided: which of its claims
have stopped being true, and where is the design itself wrong.

The design survived. The field-mapping tables, the CMMS mapping-profile schema,
the round-trip matrix, the difference taxonomy and the fail-closed labelling
needed no change. What needed changing was the schedule, the machinery around
the plan, and a handful of things nobody's slice owned.

## The schedule was a sum presented as a calendar

Slice effort adds up to 140 days across the 33 surviving slices. The plan spread
those over 26 weeks at five productive days a week with no slack, and the
allocation is uneven in a way the totals hide: the engine-and-interchange phase
carries 35 slice-days in 25 working days, export carries 27 in 20 — before the
manual native sessions, which the plan puts outside the estimate entirely — and
the final phase carries 22 days in 35.

The evidence that this already bites is in this repository. Phase 0 budgeted
eight days for the canonical model and persistence. The model landed; the
governance machinery that was not in the budget consumed the rest; persistence,
the larger half, has not started.

Effort is now recorded per slice in `docs/goals/roadmap.json` and totalled by
`sto roadmap status`, so no document carries a number that can go stale, and the
totals are labelled as slice work with review and rework on top.

## Cut-over was queued behind work parity does not ask for

`docs/evidence/PARITY-CHECKLIST.md` has fifteen items. Fourteen are delivered by
the phases before the last one; the exceptions are problems-offline and critical
updates, nine slice-days. Levelling and operational constraints appear on it
nowhere, and the frozen repositories have neither — so deferring them regresses
nothing anyone has today, while putting them first leaves a production system
frozen and unmaintained for their duration.

Split, as ADR-004. Cut-over is its own phase and comes first; levelling and
operational constraints follow, built against a stack in use.

## Two gate criteria were green on evidence that never ran

P0-G1 and P0-G3 both cite `tests/test_canonical_model.py`. Its real-schedule
class skips when the BOILER files are absent, which is every CI run. Locally the
suite reports 155 tests and no skips; in CI those criteria were being satisfied
by a class that did not execute.

Fixed by declaring the dependence rather than hiding it. A gate criterion may
now carry `evidence_conditional`, naming the switch that makes its input
mandatory; `STO_REQUIRE_BOILER=1` turns the skip into a failure;
`sto roadmap status` and `sto roadmap gate` print which criteria rest on
evidence that does not always execute; and a test binds the declaration to the
file, failing if the named switch appears nowhere in the evidence it governs —
the same binding idiom the rule registry already uses for `enforced_by`.

## What the work waits on is now data

The plan named three hard non-code dependencies in prose. Prose does not stop a
gate being marked met, and a dependency discovered in the week it is needed is
discovered too late. `docs/goals/roadmap.json` now carries six of them with the
slices and criteria each one gates, and a test refuses to let a criterion a
blocked dependency names be marked met.

Two are new to the list. The untouched source `e6a3739976580e21`, which both
evidence lines cite, is missing from this machine and from every repository, so
the calculation evidence and the native round-trip evidence have no common
baseline. And the day-5 candidate — the only status-date and progress oracle,
with no upstream anywhere — existed in exactly one copy. There are now two on
this machine and all fixture files are read-only, but both copies share one
filesystem: that is protection against deletion, not against loss, and the
off-machine copy is tracked as owed rather than assumed.

## Numbers that looked inconsistent, and were not

The conformance corpus is quoted as 36 cases, 47, 50 and "49 pass plus one
native-required" in different places. Counted from the source rather than
argued: the corpus is 50; SEM-STA-045 carries no reference forecast and needs a
native run; SEM-DET-049 and SEM-DET-050 are resource-determinism cases that
arrive with levelling; 47 remain for the CPM engine, which is exactly what the
P1 gate asks for. Every figure was right about a different subset. They are now
counted once in the roadmap data, with a test that the subsets add to the whole
and that the P1 gate and the data agree.

`dezrobbo1/PM-Software` was cloned for reference at `7a58a4f` — the corpus was
counted there, not assumed. `canonical_json.py` sits under `provenance/`, not
under `canonical/` as the plan implies.

## Corrections

`AGENTS.md` and `fixtures/README.md` both said six cases exercise real
schedules. There are eight. This is what `AGENTS.md` legislates against in its
own conventions — never write a count in prose — happening in the file that
states the rule, and no guard caught it because a guard cannot check a number
that names nothing. Both now describe the class rather than count its members.

`docs/evidence/README.md` said the register arrives with `P8`, which under the
current vocabulary is a platform slice; the register is owed to I13.

The frozen plan's header now carries a supersession block: the reconciliation
figures that were an estimate and are now a measurement, the ADR list that
diverged in subject rather than only in count, the platform-slice rename, the
withdrawn identity finding, this session's three ADRs, and two places where the
plan overstates how hard the fixtures are to obtain. The body is untouched. The
header's own "never here" rule was restated to permit exactly that pointer,
since two such notes already existed in the body and the alternative — a reader
who never reaches the live documents — is worse.

## Not done, deliberately

The `api` extra's package list and its lockfile were not written. ADR-005
settles the boundary, which is what the next slice needed; a dependency list
nothing imports and a lockfile nothing installs would be supporting work ahead
of the slice that owns it, which the working agreement defers.

The 50 conformance cases were not copied in. They arrive with the conformance
suite in S3, with the SHA-256 pins the design requires; copying them now would
put a corpus in the repository with no runner and no pin discipline.

## Housekeeping

The stale `~/Shutdown-Tracker` clone is gone, which the design plan asked for in
§E4 and which had not happened. It was 146 MB, 113 MB of it `node_modules`, and
about twenty-five merged pull requests behind its origin — the plan's "14
commits behind" reads a reference last fetched on 2026-08-17, so the real
distance was never visible from `git status`. Its working tree was clean, it
held no stashes, and its one apparently-local branch was already contained in a
remote branch, so nothing existed only there. `Shutdown-Tracker-Claude` keeps a
remote named `legacy` pointing at that path; it is now dangling, and was left
alone because that repository is frozen.
