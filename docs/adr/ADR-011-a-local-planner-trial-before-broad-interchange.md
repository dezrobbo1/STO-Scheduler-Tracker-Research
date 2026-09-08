# ADR-011: A local planner trial gates Phase 1, and the sidecar follows it

Status: accepted, 2026-09-08

## Context

Phase 1 was "Engine and interchange spine": four engine slices, the WBS
rollup, the result projection, then four slices porting the MPXJ sidecar and
retiring the Python importer, then real authentication — with the sidecar's
parity on every fixture and a native `.mpp` import as two of its six gate
criteria. Nothing in it put a calculated date in front of a user. The first
new workflow anyone could touch — imported dates beside calculated ones, an
edit that moves successors, a reset — sat behind all of that interchange work,
and behind a gate that an absent Primavera file or a sidecar that disagrees on
one fixture could hold shut.

The comprehensive repository review of 2026-09-07 said this plainly. The new
API imports and stores canonical schedules and never calls the new scheduler;
the only connected planning surface is the legacy Prototype 0 workspace on the
legacy engine; the repository is "closer to a useful local planning
demonstrator than to a live STO tracker", and the shortest credible route is
to expose one persisted, visible calculation and one edit loop before widening
compatibility. It also found the engine's most consequential defects at the
source-to-model boundary — unresolved calendars, elapsed and unknown
durations, manual and from-finish settings — and at the seams between the two
passes, none of which any interchange slice would touch.

ADR-004 already moved cut-over ahead of scheduler depth for the same reason:
order the work by what a user can see and the parity checklist asks for, not
by architectural completeness. This is the same decision one phase earlier.

## Decision

**Phase 1 is "Engine and local planner trial".** Its slices, in order: the
four engine slices already done; `C1`, source meaning preserved before
calculation (the boundary defects, each becoming a coded disposition rather
than a silent default); `C2`, the two passes agreeing on their supported
contract (the cross-pass defects the review reproduced); `S6`, rollup,
eligibility and the independent validator; `PL3`, the result projection
ADR-006 deferred; `PL13`, the calculated schedule persisted, version-bound to
its input hash and engine profiles, and visible beside the imported dates;
`PL14`, one planner scenario — a duration edit, downstream movement, reset,
export, restart; then `PL2`, real authentication, before anyone but the
planner on the loopback can reach it.

**Two gate criteria change.** The sidecar-parity and `.mpp` criteria move to
Phase 3, where the writers that need the sidecar live, as `P3-G6` and `P3-G7`;
the sidecar slices `I1`–`I4` move with them and keep their estimates. In
their place `P1-G4` asks for the trial itself: a persisted import shows
calculated dates beside imported ones, one duration edit moves its
successors, reset restores the baseline, and a restart reproduces the same
result from the same input hash. `P1-G6`, "no route accepts a trusted actor
header", was satisfiable by an API with no authentication at all and is
replaced by `P1-G5`: every route rejects an unauthenticated request, and a
project is readable only by an actor authorised on it.

**The sidecar arrives when the trial needs it.** A native `.mpp` intake, or
the Java reader as a second opinion on the Python importer, is ported when a
trial file requires it and not before; the Python importer stays the live
importer until the cross-check retires it (`PR-legacy-retirement` is
unchanged). No P6 writer, named CMMS adapter, levelling or full parity with
the frozen applications is a prerequisite for the first loop.

## Consequences

`I1`, `I2`, `I3` and `I4` leave Phase 1 for Phase 3, and `C1`, `C2`, `PL13` and
`PL14` arrive; the effort that moves with them moves with their rows, and
`sto roadmap status` is what says where the totals now stand. (This paragraph
names the slices rather than counting them: a count written here goes stale the
first time a slice is added, which is the reason `AGENTS.md` forbids it and why
`tests/test_governance_references.py` now fails on one.)
`docs/goals/ACTIVE.md`'s ordered list is rewritten from the roadmap.
The two correction slices own defects that `docs/goals/ACTIVE.md` had assigned to
finished slices or to a later writer: the unresolved-calendar loss is `C1`'s,
not S2/S3's, and `DurationFormat` is a scheduling defect before it is a
writeback one. The `P1-G2` and `P1-G3` real-schedule criteria are unchanged
and still open; the trial gate does not claim them, and the local UI may show
unsupported rows as unsupported rather than present the whole shutdown as an
operational forecast.

Rejected: keeping the sidecar in Phase 1 and adding the trial as a seventh
criterion (the trial would still wait on the sidecar); a new phase between
Phase 1 and Phase 2 (every phase id is cited by ADRs and history entries, and
a renumbering buys nothing the reorder does not); and treating the legacy
workspace as evidence that the loop already exists — it runs the legacy
engine on an in-memory document and is the comparison surface, not the
product.
