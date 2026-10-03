# PL4 live execution acceptance and sync — 2026-10-03

Starting main: `1827b1ff0bcddeb190602075f5dd04148b011291`, the merge of
PR #68. Its S7 feature head `3a68e951f31a27d9396dc1e3bc02158cccfeec9c`
is an ancestor. P1 remains 5/5 passed and P2-G1 remains met.

## Boundary and durable contract

PL4 submits an explicit S7 `ExecutionChange`; S7 alone validates Actual Start,
Actual Finish, Remaining Duration, policy, and recalculation. This slice adds
no percentage conversion, communication command, planner review, or offline
device queue. Planner or admin project membership is required to submit;
current viewer membership can read project receipts and changes. Existing
browser session plus CSRF and project-scoped device bearer authentication apply.
The actor comes from the credential, and the server rechecks credential and
membership inside the acceptance transaction. The current viewer/planner/admin
roles do not imply a new field/supervisor role.

`POST /api/projects/{project_id}/execution-operations` requires a client UUID
`operation_id`, exact `expected_version_id` and canonical `expected_hash`, a
canonical activity UUID, and supported S7 execution facts. The namespace is
`(project_id, operation_id)`. Version 1 of the semantic fingerprint hashes
parsed, canonical JSON containing schema, kind `execution`, project, actor,
expected version/hash, activity, actual dates, and remaining seconds. Retry
counter, credentials, HTTP formatting, and client clock are excluded. The
same actor, identity, and semantic values return the original receipt before
the old base precondition is reconsidered. Conflicting reuse returns
`LIVE_OPERATION_ID_CONFLICT`; a different actor cannot claim the identity.
A different project can independently use the same UUID after its own access
check. New intentions use new UUIDs.

V008 introduces separate append-only `live_execution_operations` and
`project_committed_changes` tables. The shared project change order has only
an `execution` projection today; later communication must add its own domain
row/projection and cannot enter S7 through a feed payload. Under the existing
project row lock, the operation, its full immutable `live_working` version,
stored calculation, change row, and head pointer commit atomically. The
version names the exact parent, `cause_type=progress`, and the accepted
operation row as `cause_id`. An import supersedes the movable live head while
retaining old immutable versions and operation history. A new command against
an incompatible head fails `LIVE_STALE_HEAD`; there is no last-writer-wins.
The transaction rolls back every row and cursor on a domain refusal or fault.

The applied receipt contains project/operation/actor IDs, `status=applied`,
the per-project server sequence, server `accepted_at` sampled when its change
row is written, base/result version IDs, calculation ID, canonical hash,
result fingerprint, and execution facts. It survives a lost HTTP response and
process restart. No intermediate `pending` receipt is exposed: acceptance
and the full effect are one commit. Server sequence is committed order, not
physical field-event chronology or a client timestamp. A rolled-back
allocation creates no visible gap.

`GET /api/projects/{project_id}/execution-operations/{operation_id}` retrieves
the authorised receipt; `GET /live` returns the current live head or baseline.
The live-head read rehashes its stored canonical document, and restart reports
a corrupt live head as a project integrity failure.
`GET /changes?after=N&limit=L` uses project-scoped integer cursor 0 initially,
an explicit 1–200 page bound, ascending committed rows and `next_cursor` /
`has_more`. A negative cursor is invalid; one beyond the committed maximum is
`LIVE_CURSOR_UNKNOWN`. No compaction or expiry is implemented. Authenticated
SSE at `GET /changes/stream?after=N` polls the durable feed at 250 ms,
emits committed event IDs and periodically rechecks current access. Credentials
stay in cookie/header, never the URL. A disconnected subscriber resumes by
the explicit catch-up endpoint and then subscribes from its last cursor; SSE
is a notification path, not the audit store. A slow subscriber may disconnect
and use catch-up; no broker or transient outbox is used.

Replay reads the current baseline and accepted execution rows in committed
order. It verifies their semantic fingerprints, exact parent and cause
lineage, stored canonical versions and calculations, reapplies S7 under the
recorded calculation context, and checks the final live head/hash. It does
not use today's membership, client time, notification attempts, or any
communication content. Historical operations before a later baseline import
remain auditable, while replay of the current head begins at the current
baseline.

## Executed gate evidence

`tests/test_pl4_live_operations.py` used
`tests/fixtures/synthetic-workspace-chain.mspdi.xml` on PostgreSQL 16.15.
The recorded run used baseline version
`16a5aed0-7373-4dd0-90b4-43a2e6e50446` and baseline hash
`9c783428c52d85156a1a90e848d276cd8a3121a59d23cff912cd46d003be685c`.
It accepted these sequential operation IDs on distinct activities:

1. `0c430691-44c6-5451-8836-8702f84ffdd8`
2. `ce05538d-38f3-52ed-98c8-e0f2fadc7cc9`

The resulting authoritative head version was
`2c5fe084-335e-44b6-be0c-7899c79536ee` and its hash was
`2798f4726ec9725ff5fa1c94afc4874cb3217836e844b8c9e4b47e9336233383`.
After retrying both commands and rebuilding the API/workspace, the replay
hash was exactly
`2798f4726ec9725ff5fa1c94afc4874cb3217836e844b8c9e4b47e9336233383`;
an independent Python process reopened the database and reproduced it again.
The version UUIDs above are from this executed run; they are generated
database identities and change on a fresh database. The test checks exact
parent/head equality at run time. **P2-G3 is met.**

Concurrent identical requests produced one `201`, one `200`, one cursor
position and one version effect. Concurrent distinct requests from one base
produced one accepted result and one stale refusal. Injected faults before
operation insertion, after its row was inserted but before head commit, and
after credential expiry all left no accepted state or cursor. A response lost
after commit was recovered by the same request and by receipt lookup. SSE
read no uncommitted row; after reconnect, catch-up returned missed rows in
order. A V007→V008 upgrade and repository schema-drift check passed.
The post-publication review held both the credential and enabled-user rows
through commit, acquiring them before the project lock to preserve the
account-disable lock order. A regression proves a concurrent writer cannot
lock the user row during acceptance.

P2-G2 remains **open**. No representative real-sized schedule with recorded
connected subscriber workload and enough accepted update samples was run;
the synthetic test and 250 ms polling interval are functional evidence, not
a p95 latency claim. P2-G4, G5 and G6 remain open for their later slices.

Local validation after that correction: the PostgreSQL-required focused module
passed 13 tests; the complete PostgreSQL-required suite passed 1,127 tests
with 98 conditional skips; the bare standard-library suite passed 1,125 tests
with 201 expected conditional skips. Fresh migration application and schema drift matched 8
migrations and 17 tables. Roadmap render/check, status/gate, compileall and
`git diff --check` passed. Hosted CI and its authenticated browser acceptance
are reported in the PR validation.

PL5 owns device durability and offline reconciliation; PL6 owns supervisor and
planner approval; PL7 owns broader editing; PL15 owns communication/media and
its feed projection. Their choices, including mobile framework, media
transfer, retention and notification preferences, are not made here.
