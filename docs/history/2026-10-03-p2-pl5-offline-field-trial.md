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
project, activity and semantic payload. States are queued, sending, accepted
or applied (execution only), needs_auth and needs_attention. Retry is bounded
exponential backoff from one to sixty seconds with bounded jitter. 401 holds
for same-account reauthentication; stale head, permission refusal, conflicting
identity and other permanent domain errors retain the original item for
attention. A receipt lookup before retry recovers lost acknowledgements with
the same ID. No local timestamp supplies server order.

On reconnect the client authenticates and checks project access, recovers
receipts, drains eligible intentions, then pages the durable PL4 cursor and
stores the current live head and matching calculation in one local transaction.
It rejects cursor gaps and a calculation for a different head. SSE and a
foreground timer trigger catch-up; neither is a durable source. Cache displays
last-confirmed time and offline/checking state. Local logout removes the
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

The provisional trial accepts planner/admin capability, because the current
repository has no separately evidenced field-execution/communication role.
PL15 owns the permanent communication domain, full media access/product,
messages/replies/reactions/notifications and its long-term retention policy.
PL6 and PL7 remain untouched. S7 progress semantics and PL4 acceptance
authority are unchanged.

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
