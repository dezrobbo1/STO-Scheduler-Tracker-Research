# 2026-09-20 — Field communication enters the future P2 roadmap

## Basis and outcome

Verified `origin/main` at
`4bdeff76429327984569ff5a56a005b36e5313c6`, the merge of PR #52. No later
commits were present. The independent WhatsApp-speed field-communication
review concluded **sound with corrections**. This amendment makes that
reviewed direction durable; it is not an implementation or a P1 gate decision.

The authoritative source remains `docs/goals/roadmap.json`. Its existing
generated regions in `docs/goals/ACTIVE.md` are rendered by the supported
command; the future-work narrative is maintained outside those regions.
The consolidation plan directs corrections to ADRs/ACTIVE and remains untouched.
Local numbering continues after ADR-015; PL15 was unused in the slice registry
and repository references. Existing slices retain their identifiers.

## What changed and why

P2 order is S7, PL4, PL5, PL6, PL7, PL15. PL4 owns shared authenticated,
idempotent event delivery and catch-up; PL5 owns durable offline work and an
early real-device trial; PL15 owns the bounded communication experience and its
mandatory photo/annotation recovery acceptance. PL6 review and PL7 planner
editing remain explicit authority boundaries before full PL15 delivery.

ADR-016 distinguishes communication from execution commands and excludes
communication/media from deterministic schedule state and hashes. It separates
client creation facts from canonical committed server order, requires
idempotent acceptance/effects, preserves original media, and leaves transport,
mobile framework, local database, upload and push infrastructure provisional.
The new product contract gives ordinary field communication no mandatory
classification form. Execution/Critical/Housekeeping are an initial UX trial,
not fixed domain categories.

PL9 later structures the existing messages/evidence into problems, actions and
handover. PL10 later adds schedule-derived critical monitoring; a human's
Critical post remains distinct from computed criticality. Both stay in P5.
STO activity links precede P4 CMMS enrichment. No second message/media subsystem
or CMMS dependency is introduced.

P2-G1 and P2-G3 retain their requirements. P2-G2 clarifies the accepted
execution update and recorded connected workload without widening its existing
latency target. P2-G4 retains the three-task offline report and adds two-device
communication, process termination/reopening, automatic reconnect, preserved
identity and duplicate-free acceptance/effects. P2-G5 names the existing
supervisor-then-planner rule. P2-G6 adds the communication-authority proof.
Detailed media acceptance remains at PL15, not another phase performance gate.
Every P2 criterion is still unmet; none of these future trials has run.

## Governance and effort

`PR-communication-not-authority` is pending, owed to PL15, with the future
communication package as its machinery trigger. The enforcing test must arrive
with the first accepted communication path, including an early trial.
`PR-event-idempotency` is not registered: the ADR and PL4 acceptance require
idempotency, but namespace, semantic equivalence, retention and receipt/effect
rules need a concrete enforcement boundary first.

The expanded P2 scope invalidates the old PL4/PL5 allowances; PL15 had no
allowance. Positive integer days were the only effort representation the
roadmap guard/CLI understood. A narrow governance-tooling extension permits
null only with an explanation and re-estimation point, and the status command
refuses to present a partial sum as a complete phase estimate. PL4, PL5 and
PL15 use that representation; re-estimate P2 after the PL5 device trial. Other
estimates remain unchanged. This changes roadmap bookkeeping and its tests,
not application runtime or scheduling behaviour.

Rejected: invented precise day allocations, assuming old allowances cover the
new scope, exactly-once network claims, inferred execution from message text,
mandatory classification, media in schedule hashes, a new global ordering
service, premature Capacitor/WebSocket/provider commitments, and duplicating
PL9/PL10. Detailed offline access, queue upgrade, stale activity identity,
attachment access and cleanup policies are owned design obligations, not
silently adopted implementations.

## Boundaries preserved

P1 remains 3/5, with P1-G2 and P1-G3 open. Their data, evidence and met flags are
unchanged. P2 and its slices remain not started. The S7/PL4 exception remains
proposed, not enacted, under the unchanged P1 entry decision. No scheduler,
authentication, persistence, migration, export, application UI, mobile,
transport or media implementation is included. No external/native evidence or
real-device trial is claimed by this documentation amendment.

Validation used the supported roadmap render/check, status and gate commands,
the dependency-free unittest suite, compileall and the diff whitespace check.
The suite passed with conditional external-fixture, database/API and external
PM-clone coverage skipped; no fresh native or device evidence ran. Comparison
with the starting commit confirmed unchanged P1 data, existing met flags, phase
statuses, entry-decision records, frozen design and application runtime files.
