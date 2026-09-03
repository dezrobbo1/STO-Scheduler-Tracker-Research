# 2026-09-03 — A working agreement that checks itself, and a finding withdrawn

Two things: machinery to stop the governance documents rotting, and the
withdrawal of a diagnosis that machinery could never have caught.

## Why the machinery

`AGENTS.md` was written on 2026-09-02 and reviewed the same day. Four hours old,
it asserted four things that were not true — a validation command using tools
that are not installed, and three paths that do not exist, including the
conformance suite that its own sentence about engine claims rests on.

Not a writing failure. One file was carrying statements with three different
lifetimes: durable rules that change with a decision, current status that
changes every slice, and forward commitments that come due at a gate. A document
decays at the rate of its fastest-moving part.

## What was decided

Separate the three by lifetime. `docs/goals/roadmap.json` holds what changes;
`AGENTS.md` holds what does not; two regions of `ACTIVE.md` are generated from
the data so prose cannot contradict it. The narrative around them stays
hand-written, because generating judgement would mean editing a template to
change a sentence — heavier than what it replaces, and the request was for less
ceremony, not more.

Every rule stated before it can be enforced carries a machine-evaluable
condition. When the condition is met the suite fails, names the rule, and gives
the steps to promote it. Review fires because something changed, not because a
date arrived. Between gates the mechanism is silent.

Two predicate kinds only. Running the suite from inside a predicate was
considered and rejected: re-entrant, and it asks whether something is green when
the question is whether it has arrived.

## What the guards found immediately

Six broken citations on the first run — which is the evidence they are not
vacuous. Two bare filenames; one file extension the shape test wrongly read as a
path; three paths in frozen sibling repositories without their owner prefix.
The last of those included `docs/adr/LEGACY-INDEX.md` citing the very deleted
document whose absence it exists to record, formatted as though it were live.

All fixed at the citation. None by exception — the design has no
hand-maintained exception list, because forward references are licensed by the
pending-rule registry and that permission expires by itself.

A seventh was a genuine forward reference, and licensing it surfaced a rule the
working agreement already stated and nothing tracked: the legacy package is
deleted when the sidecar cross-check is green.

Each guard was then verified by breaking it deliberately and restoring.

## What was measured, and withdrawn

The 2026-09-02 record said the assignment reconciliation split — 341 matched,
136 new, 131 missing — showed that Microsoft Project renumbers assignment UIDs,
and that assignments needed a `(task UID, resource UID)` business key.

Checking that before building it:

| Pair | Assignments | UID overlap | Proposed-key overlap | Gain |
|---|---|---|---|---|
| before → later candidate | 472 → 477 | 341 | 341 | 0 |
| before → after native progress | 472 → 478 | 341 | 341 | 0 |

Zero on both. And necessarily so: the importer derives both halves of the
proposed key *from* the Microsoft UIDs, so it is the UID under another name and
could never have matched differently. That was not checked before the claim was
written down.

The split is real churn. Of the 131, five are unassigned placeholders, thirteen
belong to a task that also went, and the rest sit on tasks that survived while
their resourcing changed. The two documents are different planning documents
with different project identities. Reconciliation was reporting the truth; a
correct result was misread as a defect.

**Withdrawn** in ADR-002 by dated amendment, and the gate criterion it produced
is replaced with one that is true and checkable: every row reported new or
missing must be attributable to a source difference. A test now holds that, and
pins the counts so a change in identity moves a number somebody re-reads.

The claim survives in two commit messages, which cannot be edited. This is the
correction.

## What this says about the machinery

The governance guards could not have caught this, and the design said so before
it happened: a claim about what a number *means* is not a claim about a path,
and no stdlib guard short of an English parser reaches it. The mitigation is the
gate ritual's human step — re-read the working agreement end to end — which is
also the argument for keeping that file short.

The rule added in response: a diagnosis is a claim, and a claim about numbers
gets measured before it is written down, including by checking that the proposed
fix would actually change the number.

## Rejected

Generating all of `ACTIVE.md`; a `test_passes` predicate; a slice dependency
graph; a JSON Schema file for the roadmap; scanning the frozen design plan,
whose 178 path-shaped references include 159 that do not resolve because it uses
one notation for three different meanings; a dev-extras group to obtain lint
tools, in exchange for a second way to run a green suite.

Also withdrawn from the plan of record: the rule that every pull request
touching source must also touch the goals file or carry a label. Per-change
ceremony trains reflexive suppression, which is the opposite of what was asked.
