# Legacy decision index

Decisions inherited from the repositories folded into this one. ADR numbering
restarts at `ADR-001` here; the entries below map what came before.

## `dezrobbo1/Shutdown-Tracker-Claude` (`STC-ADR-*`)

| Legacy | Subject | Disposition |
|---|---|---|
| STC-ADR-001 | Microsoft Project integration | Carried forward in substance; the schedule-authority clause is **withdrawn** by ADR-001. |
| STC-ADR-002 | Application architecture | Superseded by ADR-003. |
| STC-ADR-003 | Frontend and mobile | Carried forward; the offline field queue is ported. |
| STC-ADR-004 | Backend stack | Superseded by ADR-003. |
| STC-ADR-005 | Offline sync | Carried forward. |
| STC-ADR-006 | Audit and approval | Carried forward: append-only, correct-and-supersede. |
| STC-ADR-007 | Data ownership and schedule authority | **Withdrawn** by ADR-001. STO calculates the schedule. |
| STC-ADR-008 | MVP scope boundary | Withdrawn; superseded by `docs/goals/ACTIVE.md`. |
| STC-ADR-009 | UX/UI architecture | Carried forward. |
| STC-ADR-010 | Critical work package reporting | Carried forward. |
| STC-ADR-011 | Project operational mapping | Carried forward. |

## `dezrobbo1/Shutdown-Tracker` (`ST-ADR-*`)

Its `docs/adr/` directory was removed from `main` by the 2026-08-27 reset and
survives only on the archive branches. Cite by repository and commit.

| Legacy | Subject | Disposition |
|---|---|---|
| ST-ADR-012 | Trial foundation and export deferral | Historical. |

### The ADR-012 collision, resolved

`Shutdown-Tracker-Claude`'s `docs/goals/ACTIVE.md` instructed agents not to use
the number ADR-012 because it was "taken in `dezrobbo1/Shutdown-Tracker`", and
to read `docs/product/user-tier-and-assignment-model.md` in that repository
first. Both instructions were stale: the 2026-08-27 reset deleted `docs/adr/`
and `docs/product/` from that repository's `main`, so the reservation protected
a number nothing held and the pointer resolved to nothing.

Numbering restarts here, so no number is reserved and no cross-repository
pointer is load-bearing. The role-tier work that the reservation was protecting
is scheduled in `docs/goals/ACTIVE.md`; when it is written it takes the next
free number in this repository.

## `dezrobbo1/PM-Software` and this repository's own phase documents

Phase 0 and Phase 1 protocol documents remain research references under
`docs/`. They do not constrain product work. The 50-case semantic conformance
suite is adopted as the engine's specification.
