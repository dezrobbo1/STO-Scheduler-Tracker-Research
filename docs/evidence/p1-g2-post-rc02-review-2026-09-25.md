# P1-G2 post-RC02 root-cause review — 2026-09-25

Status: REVIEW COMPLETE — RC01 REMAINS THE DOMINANT OPEN FAMILY; NATIVE ASSIGNMENT MATRIX NEXT

This review starts from current main at
a4a401c42dcacfb3122467b017607aa6be1ee0e5, the merge of PR #61.

It makes no scheduler, importer, persistence, API, UI or gate change. It rebases
the P1-G2 diagnosis on the verified post-RC02 production inventory and fixes the
next evidence boundary before any further scheduling change.

## Current inventory

The post-RC02 production record is pinned by Git blob identity and reconciles to
147 unique mismatch fields across 39 leaves:

| Family | Slots | Current interpretation |
|---|---:|---|
| G2-RC01 | 143 | revalidated strong candidate |
| G2-RC03 | 3 | proven origin; replacement semantic not established |
| G2-RC04 | 1 | historical compound label requires reclassification |
| G2-RC02 | 0 | closed in production for the bounded measured semantic |

The 147 fields are:

- Start 21
- Finish 27
- Early Start 21
- Early Finish 27
- Late Start 15
- Late Finish 6
- Total Float 21
- Free Float 7
- Critical 2

P1-G2 therefore remains open. P1 remains 4/5 and P2 remains not started.

## RC01 revalidation

The ten RC01 first-divergence leaves are unchanged from the sanitized 2026-09-22
root-cause record. Every one still has the same recorded shape:

- automatic, not started, positive working duration;
- ASAP with ordinary zero-lag FS logic on both sides;
- two assignments;
- two distinct resource calendars;
- scheduled under the explicit ACTIVITY_RESOURCE_CALENDARS_UNITED assumption.

RC01 now owns 143 fields across 37 leaves. It owned 160 fields before the RC02
correction. The merged RC02 movement contract records 17 RC01 fields closed,
11 improved and 132 unchanged; no RC01 field was classified as worsened.

That does not upgrade the RC01 causal claim. The historical evidence says the
source task span equals the envelope of its stored assignment spans while STO
uses a union of resource calendars, but no independent experiment has yet
established the replacement scheduling rule. RC01 therefore remains
STRONG_CANDIDATE with replacement semantics NOT_ESTABLISHED.

No BOILER counterfactual and no production correction are authorized by this
review.

## RC03 and RC04

RC03 remains exactly three fields on two elapsed-duration roots. Its origin
remains PROVEN: the stored float values follow elapsed-coordinate gaps while the
current production float rule measures working time. The replacement contract is
still not established, so this review does not change elapsed-float production
semantics.

RC04 remains one Total Float field on L0084. Its historical diagnosis explicitly
depended on coordinate families from RC01 and RC02. Because the current
post-correction inventory has zero RC02 residual fields, that old two-parent
description is no longer accepted as a current production explanation. The slot
stays unresolved and must be reclassified after RC01; it is not authorized as an
independent fix.

## Predeclared next experiment

The next experiment is:

P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1

It is synthetic-only and must run in genuine Microsoft Project before any BOILER
counterfactual.

Its purpose is to distinguish two competing explanations:

1. the current STO approximation: schedule the task on the union of its resource
   calendars; versus
2. assignment-level scheduling: calculate each assignment on its own resource
   calendar and expose the task span as the envelope of those assignment spans.

Four bounded cases are required:

| Case | Shape | What it discriminates |
|---|---|---|
| A | two assignments on deliberately separated resource calendars | creates a task-span gap that union-calendar duration placement cannot reproduce |
| B | case A with assignment declaration order reversed | rejects assignment-order artefacts |
| C | two assignments whose calendars overlap over the complete work window | no-gap control |
| D | one resource assignment | control for the existing one-resource calendar rule |

The returned file must retain enough information to verify task Start, Finish and
Duration; each assignment Start, Finish, Work and Units; resource and calendar
identity; task type, effort-driven and IgnoreResourceCalendar settings; and the
executing Microsoft Project build.

The native rule is supported only if every condition below holds:

- each assignment span is compatible with its own resource calendar;
- each two-assignment task starts at the earliest assignment start;
- each two-assignment task finishes at the latest assignment finish;
- reversing assignment declaration order leaves the calculated result unchanged;
- the single-resource control continues to obey the existing measured rule; and
- the separated-calendar case differs from the current union-calendar placement.

Only that complete result authorizes a separate diagnostic-only BOILER RC01
counterfactual. It does not authorize production code.

## Machine-checkable record

The companion JSON is generated from the two existing sanitized evidence records
only. The reader pins both records by Git blob SHA, reconciles every one of the
147 remaining fields, verifies all ten RC01 root shapes, retains RC03's proven
status, and refuses to reuse the historical RC04 compound explanation as a
current cause.

Reproduce it with:

    python3 scripts/evidence/p1_g2_post_rc02_review.py \
      --check docs/evidence/p1-g2-post-rc02-review-2026-09-25.json

## Gate consequence

- P1-G1 — PASS
- P1-G2 — OPEN
- P1-G3 — PASS
- P1-G4 — PASS
- P1-G5 — PASS
- P1 — 4/5, IN PROGRESS
- P2 — NOT STARTED

Next action: build and run the predeclared synthetic RC01 assignment-envelope
native matrix. Do not change production scheduling semantics before that result.
