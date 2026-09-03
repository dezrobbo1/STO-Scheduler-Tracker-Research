# ADR-001: Consolidate the estate into this repository

Status: accepted, 2026-09-02

## Context

Four repositories were working the same problem — getting shutdown execution
facts into and out of Microsoft Project — and had stopped telling each other
what they found. A cross-repository review on 2026-09-02 established that:

- `Shutdown-Tracker` produced native Project round-trip evidence on 2026-08-30
  covering 13 BOILER tasks including task UID 43, with an untouched-source
  control run. `Shutdown-Tracker-Claude`'s own evidence covered task 43 alone,
  two days earlier, without a control. Neither register cited the other, and
  ST-Claude's next planned deliverable — classifying source-versus-candidate
  differences into "approved input" or "Project-calculated consequence" — had no
  category for the ten unrelated tasks the control proved Project moves by
  itself.
- ST-Claude's `docs/goals/ACTIVE.md` directed agents to two files in
  `Shutdown-Tracker` that its 2026-08-27 reset had deleted.
- The no-CPM boundary that three of ST-Claude's ADRs rest on was unknown to
  `STO-Scheduler-Tracker-Research` and `PM-Software`, both of which were
  building scheduling engines for the same domain.
- Four independent MSPDI implementations existed with no cross-check between
  them.

## Decision

This repository becomes the product monorepo. `Shutdown-Tracker-Claude` and
`Shutdown-Tracker` are frozen as references and their durable work — product
contracts, execution domain, native evidence, the MPXJ interchange service — is
ported here. `PM-Software` continues as independent research and supplies the
semantic conformance suite.

STO calculates the schedule. The frozen repositories' rule that Microsoft
Project is the schedule authority does not carry forward; it is replaced by the
boundaries in `AGENTS.md`.

## Consequences

Cross-repository pointers stop being a source of rot, because there is one
repository. The `no CPM` prohibition is lifted deliberately and recorded, rather
than being quietly contradicted by sibling repositories. The frozen repositories
keep their history and their evidence; ST-Claude stays deployed and untouched
until this repository passes the parity checklist in `docs/goals/ACTIVE.md`.

## Amendment 2026-09-03

The parity checklist this decision depends on was described as living in
`docs/goals/ACTIVE.md`, which never contained it; it existed only inside a table
cell in the design plan. It is now `docs/evidence/PARITY-CHECKLIST.md`, so the
reference is to a path a guard can check rather than to a claim about a
document's contents. The decision itself is unchanged.
