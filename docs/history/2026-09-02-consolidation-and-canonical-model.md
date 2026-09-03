# 2026-09-02 — Estate review, consolidation, and canonical model v1

Started as a review of one repository against the others. Ended with the estate
consolidated here, a direction change, and the first slice built.

## What prompted it

A cross-repository review of all seven `dezrobbo1` repositories. Four were
attacking the same problem — getting shutdown execution facts into and out of
Microsoft Project — and had stopped telling each other what they found.

## Findings from the review

1. **Evidence in one repository invalidated another's next deliverable.**
   `Shutdown-Tracker` ran a native Project round-trip on 2026-08-30 covering 13
   tasks, through an XML → MPP → reopen cycle, *with an untouched-source control
   run*. `Shutdown-Tracker-Claude`'s own record covered a single task two days
   earlier, with no control. Neither register cited the other.

   The control is the part that mattered: it showed Project by itself moved ten
   unrelated multi-assignment tasks and collapsed 2,202 timephased rows to 462,
   with no input from the tool at all. ST-Claude's planned delta classifier had
   exactly two categories — approved input, or Project-calculated consequence —
   and those ten tasks are neither. Built as specified it would have told a
   planner their progress update moved tasks it never touched.

2. **The agent contract pointed at deleted files.** ST-Claude's `ACTIVE.md`
   directed agents to `docs/adr/` and a product document in `Shutdown-Tracker`;
   the 2026-08-27 reset had deleted both from that repository's `main`. Verified
   by direct API probe — both 404.

3. **The no-CPM boundary had no standing elsewhere.** Three of ST-Claude's ADRs
   rested on Microsoft Project being the schedule authority. Neither research
   repository — both building scheduling engines for the same domain — mentioned
   ST-Claude at all.

4. **Four independent MSPDI implementations, no cross-check** between any of them.

5. The Office.js add-in that was believed to be the route around the `.mpp`
   limitation **cannot be**: the Project add-in surface is the Common API only,
   Windows desktop only, with **no assignment and no timephased API**. It cannot
   write the transaction that has actually been proven. Verified against
   Microsoft's own reference.

## Market position, checked rather than assumed

Eleven vendors read against their own pages. All are Primavera-centric and
assume an ERP is present; the only published price is a site licence at £75k a
year. Three name Microsoft Project; none documents how, and **none publishes
evidence of what survives a Project round-trip**.

Microsoft retired Project for the web in August 2025 and retires Project Online
in September 2026, while stating desktop continues — so the desktop dependency
is the surviving path, not the deprecated one.

Conclusion recorded: the defensible asset is the evidence register — a document,
a set of hashes and a build number — not any of the code.

## Decisions

- **This repository becomes the product monorepo**; the two Shutdown Tracker
  repositories are frozen references, PM-Software continues as research and
  supplies the 50-case conformance suite. (ADR-001)
- **STO calculates the schedule.** The no-CPM boundary is withdrawn explicitly
  rather than left to be quietly contradicted. (ADR-001)
- **One canonical model with durable identity.** (ADR-002)
- **Python core, Java MPXJ sidecar for file interchange**, reusing the service
  that already exists rather than hand-rolling a fourth parser. (ADR-003)
- CMMS through one work-order model and a mapped-file adapter first, then named
  SAP PM, Maximo and Oracle EAM adapters.
- "Real time" for v1: field progress reaches the *live* schedule immediately and
  reschedules the affected chain; the *approved forecast* moves only through
  review. That reconciliation is what lets both claims be true at once.

Recommended against and overruled, correctly recorded: building an own scheduler
rather than a Project-reading tracker is a longer road, and the caution was
heard and set aside deliberately.

## Built

Restructure into the `sto` package, keeping the previous engine and importer as
`sto.legacy` — every internal import was relative, so the move cost nothing and
they keep working as the oracle the new engine is checked against. Deleted an
unwired duplicate front-end that targeted an API which does not exist.

Canonical model v1: typed entities, a reflective codec, canonical hashing that
refuses floats, and identity minted as a UUIDv5 from
`(schedule_id, source_system, entity_kind, external_uid)`. The previous model
recorded `durable_cross_snapshot_identity: not_implemented`.

## Numbers from real files

Two real shutdown snapshots, ~3.4 MB each, 562 tasks, 45 calendars, 635 links.

| | |
|---|---|
| Round-trip of the canonical document | exact |
| Two imports of one file | identical hash |
| Activities keeping identity across snapshots | 447 |
| New in the later snapshot | 18 |
| Present earlier, absent later | 13 |
| Assignments matched / new / missing | 341 / 136 / 131 |

The assignment row is the finding: Microsoft Project renumbers assignment UIDs,
so they need a `(task UID, resource UID)` business key rather than their own.
The progress field contract had observed the same renumbering independently.

## Corrections made along the way

- The design pass predicted 555 matched / 7 new for the snapshot pair. Actual is
  447 / 18 / 13, and the two files carry **different project GUIDs** — treating
  them as one schedule is an operator's judgement the files do not assert. The
  command line now says so on stderr.
- Two defects were caught by the tests, both introduced in this session: an
  integer laundered into a string field, and the schema version being omitted as
  a default. A document without its discriminator is not self-describing.

## Automated review

27 findings. Nine were real and are fixed with regressions — two of them in
durable identity itself: relationships took identity from an ordinal that shifts
when a link is inserted, and rekeying left the retired key in the map so a
rekeyed row was reported as missing too. The reconciliation report always said
`missing == 0` while the command line printed a different number from a separate
calculation, so the *machine-readable* artifact was the wrong one.

Twelve were real but belong to later slices and are recorded in `ACTIVE.md`
against the slice that owns each.

Three were rejected: NFC-equivalent duplicate-key detection at the hashing
boundary, a full strict-primitive regime in the codec, and rejecting duplicate
GUIDs within a single import. Each buys a case none of our files produce, in
exchange for a new way a real schedule can stop importing. The boolean coercion
inside that third finding *was* fixed, because it could invert an activity's
meaning.

## Open, and blocking

- **No Primavera file exists anywhere in the estate.** Until one arrives the XER
  and P6 XML paths have no oracle and every P6 writer stays `diagnostic`.
- **A real CMMS extract** is needed for anything past synthetic fixtures.
- **Two schedule files have no backup.** The progress oracle exists in no
  repository and no second copy. Worse, the untouched source that *both*
  independent evidence lines cite — `e6a3739976580e21` — is on this machine
  nowhere and in no repository; it is the one point where those two lines meet.
  Recorded in `fixtures/README.md`.
