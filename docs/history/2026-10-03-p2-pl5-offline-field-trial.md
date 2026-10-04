# PL5 offline field implementation and device checkpoint — 2026-10-03

Starting main was `bb4e1d88345ff56f0d714ea999661939b86fcdc6`, the merge
of PR #69 (feature head `ee791ffe41c14e98127b3ca63e4fdcb61506da0b`).
P1 passed; S7 and PL4 were done; P2-G1 and P2-G3 were met. This work is on
`feat/p2-pl5-offline-field-app`. The final published SHA is recorded by the PR.

## Implementation

The existing planner frontend is plain JavaScript. A small separate vanilla
JavaScript field surface reuses the PL4 HTTP, receipt, change and SSE contracts
through Capacitor 8. It avoids introducing React into the existing planner.
This is a trial architecture, not a mobile-framework decision. The native
binding is community SQLite 8 with native SQLCipher encryption and a generated
secret held by the plugin's platform secure store. No web-storage fallback is
permitted. Native storage and credential protection still require genuine
device verification. Local SQL schema v1 stores execution/message intentions
and per-actor/project cursor/cache; v2 adds media and the active identity.
The transactional v1→v2 migration preserves pending IDs, payloads and cursor.

An enqueue transaction commits before the UI says “Queued locally.” Separate
execution and trial-message rows retain immutable UUIDs, original actor,
project, activity and semantic payload. Local schema v3 adds an actor/project
partitioned committed-feed projection. Its v2→v3 migration retains pending
work, media and cursor. States are queued, sending, accepted
or applied (execution only), needs_auth and needs_attention. Retry is bounded
exponential backoff from one to sixty seconds with bounded jitter. 401 holds
for same-account reauthentication; stale head, permission refusal, conflicting
identity and other permanent domain errors retain the original item for
attention. A receipt lookup before retry recovers lost acknowledgements with
the same ID. No local timestamp supplies server order.

On reconnect the client authenticates and checks project access, recovers
receipts, drains eligible intentions, then pages the durable PL4 cursor and
stores each committed event, current live head and matching calculation with
the cursor in one local transaction. Remote accepted trial notes and linked
media are projected durably and displayed separately from local intentions.
It rejects cursor gaps and a calculation for a different head. SSE and a
foreground timer trigger catch-up; neither is a durable source. A sync is
confirmed only after current authority, project access and catch-up complete;
offline/auth/access failures do not announce authoritative success. Cache displays
last-confirmed time and offline/checking state. Local logout aborts the stream
and active HTTP request, waits for the old sync to settle, then removes the
active token before clearing the protected UI while retaining encrypted,
attributed pending work for the original account. A different account sees
only its own cache, queue and media; it cannot submit the former actor's work.
Remote revocation is unknowable while genuinely offline. Current server
authority is required on reconnect. Device-token expiry/revocation and account
disable hold work for reauthentication; membership/role loss leaves an explicit
attention state. The trial retains accepted history and all pending items;
production retention/secure deletion policy needs later device/product evidence.

The bounded trial domain in V009 stores immutable text and original photo
bytes with annotation vectors, then an independent media link. It shares
PL4's committed cursor and current project access, but uses distinct tables
and routes and never invokes S7. Message acceptance does not imply photo
completion. An upload may precede its message; a retry with the same media ID
recovers upload/link acknowledgement and conflicts on changed bytes or
annotations. An unlinked remote upload remains visible for later reconciliation;
there is no silent cleanup. Original bytes are locally hashed and retained;
the canvas renders arrow/circle/text without changing the original. The
original is stored before the annotation UI opens. Media size is bounded to
5 MiB in this trial. V008 remains unedited. The schema-drift parser now handles
digits in table names. The server's calculation route permits an explicitly
selected live head so the field cache does not masquerade baseline rows as
current live rows.

## Bounded pre-device review correction

The reviewed head `ebb2ebb06deb97ee5534905b235c6369b5684eb3` exposed
account handover, false sync success, and lost remote-note projection defects.
The client now aborts/settles old-account sync before logout completes, returns
explicit sync outcomes, and commits all caught-up events atomically with its
cursor. Resume-photo failures are visible, and a failed native rollback no
longer masks the initiating transaction failure. Original-media responses are
attachments with `nosniff`; Android instrumentation checks the actual app ID.
The device-return verifier now binds its build claims to its checkout and an
authenticated, deployment-configured server build response, checks
captured baseline fields against immutable server history and the execution
base, accounts for the exact committed trial events, and requires the specified
media link/receipt and original digest. These automated corrections do not
constitute genuine-device evidence.

The follow-up reviewed head `1302cb2ea44c034ba2409b84d04c93debfbb85f0`
revealed two remaining trial defects. An unavailable authority/project check
now preserves a prior `needs_auth` state and its refusal code for execution,
notes and pending media, including the upload receipt, across local-store
reopen. The sync outcome continues to request reauthentication; only confirmed
same-actor authority/project access permits the original queue to resume.
The verifier now compares captured execution payloads and accepted receipt
facts with the prescribed starts, absent Actual Finish, remaining duration and frozen
baseline preconditions, and compares exact note text. It requires A's isolation
execution to win and the documented execution/note/link/note committed order.
Negative regressions reproduce the previous false positives. The named field
and verifier tests passed after correction; hosted validation for the final
correction head is recorded in the PR body. No physical-device trial ran.

The provisional trial accepts planner/admin capability, because the current
repository has no separately evidenced field-execution/communication role.
PL15 owns the permanent communication domain, full media access/product,
messages/replies/reactions/notifications and its long-term retention policy.
PL6 and PL7 remain untouched. S7 progress semantics and PL4 acceptance
authority are unchanged.

## Final internal pre-device audit

At reviewed head `a4a6082ac02eae60c00b3e0bff8744a18de0299d`, the trial
verifier could certify one actor acting as both devices or an unannotated
photo, and account teardown retained unsaved protected controls. The
correction binds separate authenticated device credentials and durable
receipt actors, validates the recovered arrow/circle/text vectors, and clears
all protected drafts, selections, preview and evidence text on logout. The
same audit found and corrected coherent relabelling of fixture activities,
cold-launch deep links lost before sign-in, and Android external-camera
results lost on activity reclamation. Local schema v4 preserves a pre-capture
actor/project/note/media association; restored results save the original under
that association before exposing the annotation UI. A same-actor discard
control resolves an interrupted attempt without deleting an already saved
original. The device behaviour itself remains unexecuted.

The complete internal audit traced these supported boundaries:

| Domain | Source-traced result and correction |
| --- | --- |
| A — durable outbox | Transactional enqueue and immutable IDs survive restart; states and retry bounds were traced. Local duplicate media IDs now bind activity and MIME too. |
| B — authority lifecycle | Sync cancellation settles before logout. The audit also closed delayed file-read/account-switch attribution and the protected evidence/draft teardown. Server current access still decides acceptance. |
| C — sync truth | Authority, project, receipt, submission, media, changes, live head and calculation return paths were traced. Only completed authority/project/catch-up returns confirmed; mismatched durable receipts now become permanent attention. |
| D — catch-up | Event projection and cursor/head commit in one local transaction. Gap, rollback, repeated page and restart regressions cover the feed. |
| E — domain isolation | Trial message/media routes call their distinct persistence service and committed change substrate; only explicit execution routes call S7/live publication. Communication/media never enter the canonical schedule hash. |
| F — media | Original bytes precede preview, hash is verified on read, upload/link receipts recover by immutable ID, and uncertain work is retained. Restored camera context and conflicting local identity are now explicit. |
| G — local migration | v1→v4, v2→v4 and v3→v4 tests retain queued work, needs-auth/refusal, accepted receipt, media link, committed note and cursor. Native plugin durability still needs hardware. |
| H — verifier | Exact build, two actors, pinned fixture IDs, baseline, immutable commands, notes, original digest, annotation vectors, committed order and final convergence have positive/negative mutation coverage. Device/process evidence fields are required but their physical truth needs independent review. |
| I — native packaging | Android ID/namespace/test package, manifest/deep-link/permissions and iOS bundle/Info.plist/deployment/privacy entries were source-checked; native execution remains subject to hosted Android CI and physical platform trial. |
| J — protected data | Bearer remains in headers, local evidence omits credential/photo bytes, media response is attachment/nosniff, and logout clears the protected transient surface. |
| K — state reachability | Execution queued/sending/needs-auth/needs-attention/accepted/applied; note queued/sending/needs-auth/needs-attention/accepted; media draft/queued/uploaded (recognized recovery input)/link-pending/needs-auth/needs-attention/linked were traced through retry, refusal, restart and logout. No accepted→queued path is supported; the UI's `rejected` label is not a produced persisted state. |
| L — trial feasibility | The current UI can enter the prescribed facts, notes, photo annotations and distinct statuses, and now exposes a protected read-only local evidence extract for exact manifest fields. The two-device physical sequence remains unrun. |

The verifier cannot establish that a named physical device ran a binary,
that a person used the captured token, or that process termination and media
pixels occurred. Independent install, login, lifecycle and original-photo
artifacts remain mandatory. No genuine iOS or Android device evidence is
claimed. PL5 and P2-G4 remain open; P2 effort remains unestimated until that
checkpoint. This internal audit did not request formal PR review.

## Automated evidence

The native adapter's transaction serialization, SQLite file reopen,
v1→v2 pending migration, failed enqueue rollback, actor partition, immutable
execution retry, lost acknowledgement, stale/revoked/expired outcomes, cursor
gap and recovery, communication isolation, original-media integrity and
interrupted media/link reconciliation are covered by `field/test/*.test.mjs`.
These Node tests exercise the shared SQL contract and client logic; they do
not execute the native plugin or an OS process termination.

`tests/test_pl5_trial.py` runs against PostgreSQL and proves current access,
idempotent trial acceptance/conflicting reuse, immutable activity association,
media before message, independent linking, committed mixed feed, no live-head
or schedule-hash change from text/media, and exact PL4 replay with a trial
message interleaved with execution. The focused PL4 suite remains green.
Fresh V001→V009 application and drift checks passed locally. The following
named commands passed in Work mode:

```bash
STO_REQUIRE_DB=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_pl5_trial.py -v
STO_REQUIRE_DB=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_pl4_live_operations.py
STO_REQUIRE_DB=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m sto.cli roadmap render --check
PYTHONPATH=src python3 -m sto.cli roadmap status
PYTHONPATH=src python3 -m sto.cli roadmap gate
python3 -m compileall -q src scripts tests
git diff --check
cd field && npm ci && npm test && npm run build && npx cap sync
```

Local authenticated browser acceptance could not start because the Playwright
Chromium CDN delivered a truncated archive. Hosted CI #348 at corrected head
`1d2e2e58ad191d7d62351b51a992b98146b9c6c5` passed its PostgreSQL suite,
fresh migration/drift, authenticated PL14 Chromium browser workflow, Python
3.12/3.13 bare suites, field tests/build/Capacitor sync and an Android debug
build. The final PR head's hosted result is recorded in the PR body.

## Real-device evidence and unexecuted acceptance

No genuine iOS or Android device was accessible in this Work environment.
Capacitor generated iOS/Android native project shells and copied web assets;
CI assembled an Android debug build. Neither a genuine-device build/run nor
the native SQLCipher runtime, OS lifecycle,
camera permissions, secure-secret persistence, background/suspend, force-quit,
device reboot, network transitions, app upgrade, push/deep link, or interrupted
binary transfer has been observed on hardware. The simulator/emulator and
Node tests are not substituted for these observations. The deterministic
return procedure is in `docs/evidence/pl5-device-return.md` and the server
verifier is `scripts/verify-pl5-device-trial.py`.

The mobile architecture and local database are **NOT ESTABLISHED** on genuine
devices. PL5 remains not complete, P2-G4 remains open, and P2 effort is not
re-estimated. P2-G2 has no representative connected p95 workload and remains
open. P2-G1 and P2-G3 remain met; P2-G5 and P2-G6 remain open.
