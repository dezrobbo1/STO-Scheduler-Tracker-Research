# P2 development continuation while physical acceptance remains open

Owner-authorized sequencing decision: 2026-10-10.

This is a development-only exception to the default intra-P2 order in
`docs/goals/ACTIVE.md` and `docs/goals/roadmap.json`. It does not change phase
entry, any gate criterion, slice acceptance, security invariants, or merge
approval. It supersedes only the interpretation that unfinished PL5 physical
acceptance prevents all PL6/PL7 implementation. ADR-016's separation of
communication, execution authority and approved-forecast review still applies.

## Permission and limits

Independent **PL6 server/browser review and approved-forecast work may proceed**
while PL5 physical acceptance and P2-G4 remain open. Independent **PL7
server/browser editing, lease and scenario work may follow**, respecting any
actual PL6 dependency. They need not wait for the entire additional mobile
cloud campaign. Each task must identify its dependency boundary and its own
required evidence before implementation.

This permission is not acceptance of the mobile architecture for field use.
PL5 remains incomplete. P2-G4 and PL15's physical-device acceptance remain
mandatory before P2 closure; an emulator or simulator result cannot mark them
met. Later phases do not start under this exception. Do not mark a slice done
merely because work on the next slice is permitted.

Independent PL6/PL7 work may be reviewed on its own declared acceptance rather
than blocked solely by P2-G4. This decision neither merges PR #70 nor authorizes
automatic merges of follow-up work. Every merge still needs explicit owner
instruction and the applicable review/CI evidence. No implementation or cloud
extension is claimed completed by this documentation change.

## Evidence baseline and what it does not establish

The preserved PL5 cloud reference is commit
`f7382cba23913aa8a8a966d46e0a8867cc7ccd13` on
[PR #70](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/pull/70).
Its [Android cloud run #22](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/actions/runs/37775847876)
and [CI #381](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/actions/runs/37775847900)
passed. The source-bound
[cloud evidence record](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/f7382cba23913aa8a8a966d46e0a8867cc7ccd13/docs/evidence/pl5-cloud-emulator.md)
defines their limits:

- Android exercises native encrypted storage, unavailable-server queueing,
  force-stop/offline reopen, reconciliation, account handover, deep links and
  synthetic media through production handlers. A-to-B handover on an
  installation is not the full independent-client conflict sequence.
- iOS proves native build/install/launch, rendered WebView, encrypted database
  startup and bounded process survival. It does not establish Android-level
  behavioural coverage.
- The host-side field suite already covers lost acknowledgements, expired or
  revoked authority, account isolation, media recovery and schema migration.
  Its SQLite adapter and simulated transport are not full native integration
  evidence. Reuse those tests rather than duplicating every case in UI tests.

The field suite and API evidence remain source-specific; see the pinned
[field tests](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/f7382cba23913aa8a8a966d46e0a8867cc7ccd13/field/test/field.test.mjs)
and [PL5 API tests](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/f7382cba23913aa8a8a966d46e0a8867cc7ccd13/tests/test_pl5_trial.py).
These links identify unmerged PR content, not files claimed to exist on main.
Hosted freeze verification is separate from native application testing; it
cannot fill a missing native flow or certify the original physical tokens.

Do not infer that future hardware failures will be minor, or assign a
probability to that claim. A preserved source commit aids diagnosis; it is not
a tested rollback of migrated data, signing state or later dependent features.

## Focused cloud extension: planned, not executed by this decision

This is an extension of PL5 evidence, **not a new phase gate or a blanket
prerequisite for PL6/PL7**. Before work begins, inventory existing evidence and
reuse the production handlers, API and native store. Keep detailed failure
combinations in component/API tests; use representative native integration
flows for the boundaries below.

| Boundary | Required additional evidence | When it matters |
|---|---|---|
| iOS behavioural recovery | Disposable authenticated backend; queue execution, a note and synthetic annotated media; terminate; reopen offline; reconnect. Bind unchanged UUIDs, payloads, ownership and media digest to durable final states, receipts and matching cursor/hash. Exercise account handover with A's pending work inaccessible to B. | Before substantial expansion depending on iOS field behaviour. |
| Independent-client conflict | Distinct authenticated actors on independent native app installations with separate local stores, both holding commands against the same baseline. Control reconnect order and verify the prescribed accepted effect, visible stale-head refusals, notes/media and final convergence. Never silently rebase or replace IDs. | Before broader multi-user field functionality relies on that boundary; not before isolated PL6 server work. |
| Native failure recovery | Observe a server commit before dropping the acknowledgement, then reconcile the same operation ID without a duplicate accepted effect. In separate controlled cases invalidate credentials or project authority while work is queued, and interrupt media upload and link recovery. Preserve work and enforce current authority. | Before relying on those integrations for mobile expansion. A demonstrated security, loss or false-success defect blocks the affected integration. |
| Upgrade persistence | Retain schema regressions; add native old-store to new-store evidence before the next storage migration or supported upgrade claim. Preserve pending payloads, receipts, actor partitions, media, cursor and encryption-secret access. | Before changing that contract or claiming upgrade support; not a prerequisite for unrelated planner work. |
| Emulator cold restart | Where deterministic, cold-restart the virtual device with persistent app data and verify durable recovery. Restoring a running snapshot is not reboot evidence. | Useful supplementary evidence, not a blanket PL6/PL7 prerequisite. A reproduced durability defect is still material. |

For independent-client coverage, use a shared disposable backend and genuinely
separate stores; a serial account switch in the same app does not substitute.
A first cross-platform campaign is useful when practical, but do not create a
large coordination system solely to run the same platform-independent conflict
logic. Record exactly which platforms and installation boundaries executed.

Fault injection must identify the boundary it actually reached: server
unavailable before submission is not a lost post-commit acknowledgement;
interrupted upload and lost link receipt are different cases. Authority
coverage must demonstrate the actual backend denial, no newly accepted work
under stale authority, preserved attribution, and permitted recovery under the
existing state machine. Do not grant new authority by replaying old queues.

Use explicit readiness/completion observations and bounded timeouts rather
than fixed sleeps. Do not bypass production authentication, weaken TLS, replace
the native store with a mock, or alter acceptance assertions just to pass.
Keep the environment and credentials disposable and separate from Railway's
pristine trial project. Redact and scan evidence before upload.

Record each case as PASS, FAIL, UNEXECUTED or INFRASTRUCTURE BLOCKED, with its
exact source SHA, native build identity, scenario and evidence. Seeded-schema
migration is not an actual old-app to new-app installation upgrade. Synthetic
file-handler input is not camera or OS-picker evidence. Runner instability
must not be presented as either product failure or PASS; a concrete data-loss,
authority or false-success defect must not be dismissed as flakiness.

## Boundaries that keep continued development reversible

PL6/PL7 consume defined execution, receipt, version and review contracts. They
must not depend directly on native SQLite tables, camera-restoration details
or platform secret-store internals. Preserve immutable operation identity,
actor/project ownership, expected-version/hash checks, append-only audit,
communication/hash isolation and distinct supervisor/planner approval.

A proposed change to those contracts is not routine independent continuation.
Review its affected callers, pending queues, compatibility and evidence before
integration. Keep migrations append-only. Verify old-store handling before a
schema change; never assume restoring old code can safely downgrade new data.
A finding blocks work that depends on the affected boundary, not unrelated
work merely because both are in P2.

## Branch, evidence and deployment discipline

Preserve PR #70's reference head and its existing evidence. Do not amend it,
mark it Ready, merge it, or re-pin the frozen Railway API as a side effect of
this policy update. Keep the pristine hosted trial project and credentials out
of additional cloud tests.

Start independent PL6/PL7 work from verified main where its dependencies are
already merged. If a task genuinely requires unmerged PL5 changes, declare a
separate dependent branch/PR and its exact base before writing; do not silently
cherry-pick PL5 into an allegedly independent PR. Review inherited changes
separately and do not merge a dependency stack without explicit authorization.
Additional mobile harness work likewise uses an explicitly scoped follow-up,
not an unannounced mutation of the frozen reference.

Retain safe evidence and hashes outside expiring CI artifact storage before
relying on them long term. This decision records the source/run references; it
does not claim that an independent permanent artifact archive has been made.
New cloud evidence belongs to the commit actually tested. Later physical
acceptance must use its own exact app/server/verifier source and installation
provenance; the earlier f7382cba reference cannot certify a changed build.
No Railway deployment change or credential operation is authorized by this
sequencing decision.

## Physical checkpoint and final acceptance

Run the physical iOS/Android campaign at the **first representative PL15 field
workflow**, before substantial further mobile-dependent expansion. It must be
representative of execution, offline recovery, communication and media; final
visual polish is not a prerequisite. Do not defer it until the whole app is
finished. Relevant cloud integration evidence is required before broader
mobile reliance, but is not a replacement for this checkpoint.

Carry the existing
[physical return procedure](https://github.com/dezrobbo1/STO-Scheduler-Tracker-Research/blob/f7382cba23913aa8a8a966d46e0a8867cc7ccd13/docs/evidence/pl5-device-return.md)
forward explicitly to the selected candidate. Preserve its execution/ordering,
local-state, authority, original-media and lifecycle requirements. A changed UI
may require a reviewed procedure adaptation, not a silent waiver or fabricated
evidence. Reassess P2 effort after hardware results; unknown effort remains
unknown.

Keep these decisions separate: permission for continued development; physical
PL5 acceptance; and completion of P2. P2-G4, PL15's real-device acceptance and
all other open P2 criteria remain required for P2 closure and any release
claim depending on them. No additional evidence pass is claimed here.
