# PL5 genuine-device return package

This is an unexecuted procedure. Fill a private manifest with synthetic trial
IDs and evidence filenames; do not commit credentials or private photos. Use
the exact PR head SHA as both app and server build SHA, and apply through V009.
Native targets currently declare Android API 24 minimum and iOS 15.0 minimum.
The trial requires one physical iOS device and one physical Android device.

## Prepare

1. On the server SHA, install the API extras, apply migrations with
   `scripts/db/apply-migrations.sh`, and serve HTTPS reachable from both
   devices. Start with a fresh synthetic project; import
   `tests/fixtures/synthetic-workspace-chain.mspdi.xml`, calculate the baseline,
   and record the `GET /live` version/hash and `GET /changes?after=0` cursor.
   Confirm activity identities returned by `GET /calculations/latest` for
   **Isolate equipment**, **Execute inspection**, **Restore equipment**;
   expected source GUIDs end `0002`, `0003`, `0004` respectively. Record actual
   canonical activity UUIDs from the API, not from the file alone.
2. Create two separate synthetic planner-member users and project-scoped
   device tokens through the existing admin API. Keep raw tokens off the
   evidence files. Install the same PR-head `field/` native build on both
   physical devices: `cd field && npm ci && npm run sync`, then use Xcode on
   macOS for iOS and Android Studio/Gradle SDK for Android. Record actual app
   version/build SHA, device model, OS version and install method. No release
   signing keys belong in git.
3. Sign in separately. Confirm each device has cached the same live
   version/hash, activity names and committed cursor. Record screenshots
   `A-00-online`, `B-00-online`, and a server baseline JSON export.

## Exact offline sequence

1. Put **both** devices in airplane mode and verify no server reachability.
   Device A queues an Actual Start `2026-01-05T09:00:00`, remaining 1 hour
   for Isolate equipment; then a note “A: isolation observed” on that task.
   Device A also queues Actual Start `2026-01-05T13:00:00`, remaining 1 hour
   for Execute inspection. Device B queues Actual Start
   `2026-01-06T08:00:00`, remaining 1 hour for Restore equipment, and a note
   “B: restore observed” on that task. Record the three execution UUIDs,
   two message UUIDs, exact activity IDs, local creation order and visible
   queued states from the UI. If a date is refused by the S7 fixture context
   during the controlled trial, record the actual stable refusal and stop;
   do not silently change the original command.
2. On A capture/select one synthetic photo, draw arrow, circle and short
   text, and queue it against A's note. Preserve screenshot of queued photo,
   annotation and SHA-256 of the original. Interrupt transfer later during
   reconnect; compare original SHA after retry. Continue normal UI work while
   media is pending.
3. Terminate both app **processes** with the OS application switcher/process
   controls, distinct from merely backgrounding. Reopen both while still
   offline. Record `A-01-reopen` and `B-01-reopen`: all three execution
   intentions, both notes and the photo must retain UUIDs, activity IDs and
   queued state. Capture separate suspension, explicit force-quit/force-stop,
   and OS reclamation evidence only if those actions are actually run.
4. Reconnect A first, leaving B offline. A's first execution should be
   accepted/applied and its second should become `LIVE_STALE_HEAD` needs
   attention: both commands were frozen against the same baseline. A's note
   must be accepted. Interrupt photo upload, reopen/reconnect, then verify
   idempotent upload/link and unmodified original. Record receipt/cursor,
   local attention state and photo state. Then reconnect B. B's execution
   should become `LIVE_STALE_HEAD` needs attention; B's note must be accepted.
   This is an explicit PL4 global-head conflict, not lost field work. Do not
   rebase or assign new IDs to the two stale commands. Both clients catch up
   the committed order and agree on final live hash. The server has exactly
   one accepted execution effect, two accepted notes and at most one link
   event. These are the expected outcomes for this frozen-base trial; if
   P2-G4 interpretation demands three *accepted* execution effects, this
   trial alone does not close the gate and a separately sequenced device run
   must be designed without silently rebasing offline work.

## Additional lifecycle matrix

Record each case separately with model/OS/build, before/after local UUIDs,
cursor, server response and evidence filename: online; airplane mode;
intermittent network; Wi-Fi→cellular; background/suspend; actual process
termination; explicit force-quit/force-stop; offline reopen; reconnect; lost
HTTP acknowledgement after server commit (same ID/receipt); token expiry;
server membership revoke/role downgrade while offline; account disable;
device-token revoke; logout and Account A→B switch; device reboot; old build
with pending v1 store→new v2 build upgrade; interrupted media transfer; deep
link `sto-field://project/<project-id>/activity/<activity-id>` after fresh
auth/catch-up. Mark unrun entries **unexecuted**, rather than “pass”. Remote
revocation cannot be known before network contact. Do not treat push arrival
as authority; production push infrastructure is not installed by this trial.

## Return and verify

Return the server baseline/final `GET /live`, paged committed feed JSON,
execution receipts, trial message/media receipts, device screenshots and a
redacted `manifest.json`. The manifest keys are `server` (HTTPS), `project_id`,
`baseline_hash`, `baseline_version_id`, `baseline_cursor`, `server_sha`,
`app_sha`, `final_hash`, `device_a`, `device_b`, `execution` (three objects with
`operation_id`, `activity_uid`, `local_final_state`, `error_code`), and
`communication` (two objects with `id`, `activity_uid`). Device entries need
`model`, `os`, `app_sha`, `offline_evidence`, `termination_evidence`,
`reopen_evidence`, `reconnect_evidence`, `final_cursor`, `final_hash`. The stale two must have
`local_final_state=needs_attention`, `error_code=LIVE_STALE_HEAD`.

Run with a current viewer token stored only in the environment:

```bash
STO_TRIAL_VERIFY_TOKEN=... python3 scripts/verify-pl5-device-trial.py manifest.json
```

The verifier fails closed on missing evidence fields, cursor gaps, missing or
duplicate accepted records, stale items lacking attention state, changed
activity links, or a final hash that differs from the accepted execution.
Inspect returned device evidence and lifecycle matrix separately before
deciding PL5/P2-G4. This script does not certify a photo's pixels, genuine
device model, process termination or storage encryption by itself.
