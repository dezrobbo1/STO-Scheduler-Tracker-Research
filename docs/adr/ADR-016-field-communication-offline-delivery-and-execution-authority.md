# ADR-016: Field communication, offline delivery and execution authority

Status: accepted for future P2 design, 2026-09-20; implementation not started.

## Context

The field-communication research and independent roadmap review concluded
"sound with corrections": immediate text and annotated photographs belong
beside the live execution loop, using its delivery and offline foundations.
They add product scope beyond a progress-report form. Putting that scope into
S7 would confuse descriptive information with scheduling inputs; burying it in
PL4 or PL5 would hide the work and duplicate later evidence workflows.

This decision amends the future design through `docs/goals/roadmap.json` and
`docs/goals/ACTIVE.md`. It leaves the frozen
`docs/roadmap/CONSOLIDATION-PLAN.md` unchanged. P1 evidence remains open under
`docs/evidence/p1-gate-entry-decision-2026-09-20.md`; neither this decision nor
the device trial below enacts its proposed S7/PL4 exception or permits P2 to
start before the existing entry requirements are satisfied.

## Decisions

### Communication is context; execution commands carry authority

The following examples are synthetic.

| Concept | Example | Authority |
|---|---|---|
| `CommunicationEvent` | "A-101 bolts seized. Probably another 45 min." | Describes the situation; can reference an activity, image or user. |
| `ExecutionCommand` | "Set A-101 remaining duration to 3 hours." | An explicit request, separately authorised, validated and audited; its accepted effect can cause S7 recalculation. |

A communication cannot set actual start, actual finish, remaining duration,
progress, live schedule state or approved forecast. Natural language implying
completion or delay confers no authority. A message may offer **Mark complete**
or another action, but the user must submit a separate execution command with
its own identity, permission check, domain validation and audit lineage. A
reaction, mention, Critical placement or notification acknowledgement is not
execution or review approval.

S7 owns supported execution semantics and deterministic recalculation, including
incremental/full equivalence. ADR-009 still governs dates and remaining
duration; percentage conversion is an explicit API-edge obligation, not text
interpretation. PL6 owns supervisor then planner review and approved forecast;
PL7 owns planner editing, leases and scenarios. Sending communication needs no
planner edit lease and grants no planner or supervisor power.

Communication text, replies, reactions, photographs, annotations, delivery
state and notification state remain outside canonical scheduling inputs,
deterministic calculation state and schedule hashes. They can reference
schedule/activity identities and immutable version provenance. They must not
be copied into canonical activity notes or another hashed field as a shortcut.
An execution command's accepted authoritative effects remain separately
modelled and replayable through the version envelope in ADR-007.

### Share delivery, not domain objects

PL4 owns authenticated submission, immutable client operation identity,
idempotent acceptance and effects, audit, realtime subscription and explicit
catch-up/sync. Execution and communication can share that infrastructure while
keeping separate schemas, validation, permissions and projections. A shared
feed is not a universal domain event whose arbitrary payload reaches the
scheduler. A system event shown in a timeline is a labelled projection of its
source event; displaying or replaying it cannot execute its command again.

Accepted operation history is append-only: corrections, supersession and
retractions record new facts and retain provenance. Drafts, local outbox retry
state and read cursors are operational state, not an immutable audit ledger.
Media retention or authorised removal must leave an attributed record under a
defined policy; immutability does not invent indefinite storage or unrestricted
access to every original.

### Identity, acceptance and effects survive retries

Each submitted operation has an immutable client-generated identity that
survives retries, reconnect and process restart. Within its defined authority
scope, the same identity and same operation semantics returns the existing
accepted result without accepting or applying it again. Conflicting reuse is
refused. The server binds identity to authenticated actor, project, operation
type, target and immutable semantic payload; clients cannot change those
bindings by claiming a different author.

PL4 must define and version the semantic fingerprint and identity namespace.
Execution preconditions and attachment references are part of the operation's
meaning; refreshed authentication credentials and retry counters are not. A
new intention or a correction uses a new operation identity. An acceptance
receipt distinguishes accepted, pending application and applied outcomes;
acceptance cannot falsely claim that media uploaded or recalculation finished.

The acceptance record, effects and their recovery must prevent a crash or lost
acknowledgement from creating a second accepted operation, attachment or
execution effect. Concurrent retries are part of this obligation. Authenticate
and check receipt visibility before returning a prior result; recognise an
already accepted identical operation before treating its original version
precondition as a new stale command. PL4/S7 must define the atomicity or
recoverable lifecycle that makes this true. This is idempotent acceptance and
effects over retrying delivery, not an exactly-once network guarantee.

### Client chronology and server order are different facts

Preserve concepts equivalent to the following; these are not a prescribed wire
schema or storage technology.

| Fact | Meaning |
|---|---|
| Client operation ID | Immutable identity, not a timestamp or ordering claim. |
| Local/device sequence | The originating queue's order, scoped to its device/queue incarnation where required. |
| Client creation time | Device-observed time, potentially skewed or wrong. |
| Server acceptance time | Authoritative time of receipt/acceptance, not when the field event happened. |
| Server acceptance sequence | Canonical committed order within the declared project/feed scope, used for catch-up and replay. |

Independently offline devices do not supply a knowable global creation
chronology. Reconnect preserves their local facts and establishes server
acceptance order; it does not backdate authority or sort execution by an
untrusted client clock. Local ordering and dependency references preserve
causality where required, such as a reply or annotation referring to its
parent. They need not block unrelated execution behind a large photograph.

A catch-up cursor must not skip an event that commits after a later-numbered
event has been exposed. A sequence allocated before commit is not, by itself,
proof of committed delivery order. The implementation and cursor scope remain
PL4 design work; no globally ordered infrastructure across all projects is
required. Schedule replay folds recorded authoritative execution effects in
their defined order and reproduces the head hash, independent of communication
traffic, client clocks or today's membership changes. Stale or conflicting
execution commands require explicit domain resolution; canonical ordering
does not make silent last-writer-wins safe.

### Offline interaction is durable, but does not grant authority

PL5 owns durable local state, useful cached field state, immediate optimistic
interaction and a durable outbox for commands, communication and media
references/transfers. Queued, accepted, applied and failed states must remain
distinguishable. Queuing is not authoritative live progress or confirmed
delivery. Ordinary network loss should recover automatically; a permanent
permission or domain refusal needs an understandable resolution, not endless
retries or silent deletion.

ADR-014's current user, membership and credential checks remain the starting
authority boundary. Newly submitted offline work must pass server acceptance
under the operation's authoritative rules. Former permission at creation time
is not an exemption for an expired session, disabled account, revoked project
membership or changed capability. No creation-time authority grace period is
adopted here. Reauthentication may resume work still permitted for its original
actor/project; it cannot relabel old queued work as another account's work.
Historical replay reproduces recorded accepted effects; it does not submit
those old commands anew under current permissions.

PL4/PL5 must specify the detailed acceptance/application policy, stale-command
resolution, long-offline bounds and rejected-work retention before enabling
submission. PL5 must also resolve logout, account switching, device loss,
cache visibility and credential renewal without weakening ADR-015's immediate
protected-UI clearing or truthful logout. An offline device cannot learn a
revocation instantly; its bounded local-access policy must acknowledge that
limit. Communication capabilities must be distinct from schedule powers; the
current viewer/planner/admin roles are not evidence that field/supervisor
capabilities already exist.

### Preserve activity and media provenance

Activity links use STO's canonical identity with project and relevant version
context, following ADR-002/ADR-007. Re-import must preserve historical links
even if the activity departs the current schedule. Missing or ambiguous
identity is explicit; never silently relink by display name or apparent row
position. The known business-key integration gap in `docs/goals/ACTIVE.md`
remains real. Communication does not wait for P4: work-order and equipment
context can enrich an existing STO activity link when CMMS integration arrives.

Photo markup preserves the immutable source independently of its annotation.
The conceptual model supports the original, a field-optimised derivative where
useful, an annotation/vector representation and a rendered annotated image
where useful. Accepted annotation revisions retain their relation to the
original; the current rendering does not overwrite source evidence.

Media transfer must be nonblocking, recoverable and idempotent at the attachment
record boundary. A message accepted with pending media and a photo uploaded
before message acceptance are different recoverable states. PL5/PL15 must
define their linkage, integrity checks, local storage limits, orphan cleanup
and retention before the field trial claims success. Project access controls
apply to original images, derivatives, thumbnails and notification/deep-link
fetches, not only the message. Exact formats, transfer protocol and storage
provider are not decided here.

### A bounded communication product, then structured operations

PL15 owns the behaviour in `docs/product/field-communication.md`. Execution,
Critical and Housekeeping are the initial communication UX configuration to
trial, not immutable domain categories or mandatory classifications. A normal
message requires no classification form. Replies, mentions, simple reactions,
photos, markup, activity context and useful notifications are the initial
scope; arbitrary team/channel hierarchies and general collaboration are not.

PL9 remains in P5 and adds problems, actions, ownership, due dates and handover
around PL15's existing communication/evidence identities. It must not recreate
the messaging or media subsystem. A supported problem-induced execution
change still uses an explicit authorised execution operation.

PL10 remains in P5 and adds schedule-driven critical watch, near-critical
monitoring, escalation and reporting periods. Human Critical placement and
calculated criticality remain separate facts. Historical calculated context
names its schedule version; a later calculation can change current criticality
without rewriting what a person posted or what was calculated then.

## Provisional choices and proof

| Topic | Current direction and evidence still required |
|---|---|
| Mobile client | React plus Capacitor is a strong candidate, not committed architecture. Real iOS and Android devices must prove durable storage, suspension, process termination, reconnect, queued state, push deep links, media recovery and authentication/session lifecycle. |
| Realtime | Authenticated HTTP POST plus SSE and explicit catch-up is the preferred simple candidate. Validate connection authentication, packaged-client behaviour, credential renewal, suspension/resume and missed events before committing. Realtime subscription is the roadmap requirement; neither WebSockets nor a managed provider is mandated. |
| Local storage | Database, migrations for queued client work and secure credential storage await the mobile proof; no database or new credential scheme is selected. |
| Media | Resumable protocol, background/native transfer boundary, object storage, derivative formats and upload tooling await device evidence. |
| Notifications | Push infrastructure, subscription preferences and background limits await the trial. Push is a hint to authenticated sync, not acceptance, delivery proof or a guaranteed critical alert. |

After legitimate P2 entry and S7/PL4 foundations, PL5 runs a thin integrated
text/photo/annotation/device experiment before the full PL15 experience. Its
purpose is to select the mobile/offline boundary and re-estimate effort. It is
not authority to implement now or evidence that PL15 is complete. Full delivery
order is S7, PL4, PL5, PL6, PL7, PL15.

P2 retains incremental/full equivalence, scoped live propagation, log replay
and approved-forecast governance. The strengthened offline trial retains the
original three-task report and adds both-device offline communication,
application process termination/reopening and duplicate-free accepted effects.
A separate gate checks the communication/command authority boundary. Detailed
media recovery is mandatory PL15 acceptance in the product contract, not an
additional whole-phase performance gate. A phase cannot close with its
communication slice's mandatory acceptance unfinished.

## Governance and consequences

`PR-communication-not-authority` is a stable cross-cutting invariant, pending
and owed to PL15. Its machinery trigger is `src/sto/communication`; when the
first accepted communication path arrives, including an early trial, promote
the rule with an enforcing test proving schedule state/hash isolation and the
separate authorised-command path. If the implementation locates that machinery
elsewhere, update the trigger in the same change, before it can accept work.

Do not register `PR-event-idempotency` yet. PL4 acceptance requires the property
now as a design obligation, but its namespace, semantic equivalence, receipt
visibility, retention and application lifecycle still need a concrete contract.
There is no reliable generic enforcement owner covering every future operation
yet; copying the sentence into a pending rule would add ceremony without a
better trigger.

P2 grows materially. PL4/PL5 allowances are superseded and PL15 is unestimated
until the device trial; roadmap bookkeeping represents unknown effort
explicitly, never as zero. No application, scheduling, authentication,
persistence, migration, export or transport behaviour is introduced by this
decision. Voice, video, incident rooms, automated handover, advanced critical
analytics and AI operational summaries remain deferred.
