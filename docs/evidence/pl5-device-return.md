# PL5 genuine-device return package

This is an unexecuted procedure. Fill a private manifest with synthetic trial
IDs and evidence filenames; do not commit credentials or private photos. Run
the verifier from a checkout of the exact PR head SHA used for both app and
server; it refuses a manifest naming another SHA. Set `STO_BUILD_SHA` to that
commit in the server deployment environment before API startup, then capture
the authenticated `GET /api/trial-build` response; the verifier refuses an
absent or different deployed identity. Independently retain the server
deployment/build log and each native install/build record to establish
that those binaries really came from that checkout. Apply through V009.
Native targets currently declare Android API 24 minimum and iOS 15.0 minimum.
The trial requires one physical iOS device and one physical Android device.

## Prepare

1. On the server SHA, install the API extras, apply migrations with
   `scripts/db/apply-migrations.sh`, and serve HTTPS reachable from both
   devices. Start with a fresh synthetic project; import
   `tests/fixtures/synthetic-workspace-chain.mspdi.xml`, calculate the baseline,
   and save the complete `GET /live` and `GET /changes?after=0` JSON in
   `baseline_server.live` and `baseline_server.changes` before either device
   goes offline. Require an empty feed and cursor zero; the verifier also
   checks the immutable `/versions` entry and accepted execution's base.
   Save the authenticated `GET /calculations/latest?kind=baseline` response.
   Confirm activity identities returned for
   **Isolate equipment**, **Execute inspection**, **Restore equipment**;
   the fixture's canonical activity UUIDs are respectively
   `0d717f24-85ff-5d98-afce-2fcaf8bbb5cf`,
   `1256e448-70c8-5839-8a89-9300d703d276`, and
   `88f5407a-79c8-5501-a94a-50d91104ac0d` (source GUIDs end
   `0002`, `0003`, `0004`). The verifier checks both the pinned IDs and the
   authenticated baseline calculation names/version/hash.
2. Create two separate synthetic planner-member users and project-scoped
   device tokens through the existing admin API. Keep raw tokens off the
   evidence files. Install the same PR-head `field/` native build on both
   physical devices: `cd field && npm ci && npm run sync`, then use Xcode on
   macOS for iOS and Android Studio/Gradle SDK for Android. Record actual app
   version/build SHA, device model, OS version and install method. No release
   signing keys belong in git.
3. Sign in separately. Capture each device's authenticated
   `GET /api/auth/session` actor response as `authority_evidence` and record
   its `user_id` as `actor_user_id`. The two actors must be different. Keep
   both device tokens available only as `STO_TRIAL_VERIFY_TOKEN_A` and
   `STO_TRIAL_VERIFY_TOKEN_B` in the verifier environment; it independently
   authenticates both and checks current trial-project access. Confirm each device has cached the same live
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
   queued states from the UI. Retain each exact local execution `payload`
   before drain (including baseline version/hash and all execution facts),
   and each note's exact `text`; the verifier binds them to this prescribed
   sequence. The execution array order is A isolation, A inspection, B restore;
   the communication array order is A isolation note, B restore note.
   Tap **Show synthetic trial evidence** on each signed-in device after queueing
   and again after reconnect. Copy its read-only actor, frozen payload, note,
   media digest/annotation and final state fields into the private manifest;
   it excludes credentials and original bytes and clears on logout. The actual
   `/api/auth/session` response and independent device evidence still need
   separate capture; the local export alone does not prove physical provenance.
   If a date is refused by the S7 fixture context
   during the controlled trial, record the actual stable refusal and stop;
   do not silently change the original command.
2. On A capture/select one synthetic photo, draw arrow, circle and short
   text, and queue it against A's note. Preserve screenshot of queued photo,
   annotation and SHA-256 of the original. Record the immutable media UUID,
   owning A note UUID and activity UUID. Interrupt transfer later during
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
   one accepted execution effect, two accepted notes and exactly one expected
   link event with the recorded media/message relationship. These are the
   expected outcomes for this frozen-base trial. The exact committed order is
   A isolation execution, A isolation note, its recovered media link, then B
   restore note. Keep B offline until that link is confirmed; any other winner
   or committed order fails this procedure's verifier. If
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
with pending v2/v3 store→new v4 build upgrade (and v1→v4 where available);
interrupted media transfer; deep
link `sto-field://project/<project-id>/activity/<activity-id>` on cold launch
while signed out and after fresh
auth/catch-up. Mark unrun entries **unexecuted**, rather than “pass”. Remote
revocation cannot be known before network contact. Do not treat push arrival
as authority; production push infrastructure is not installed by this trial.
On Android, also launch the camera, let the OS reclaim the app while the
external camera activity is open, and confirm `appRestoredResult` recovers the
original under the same account, note and media ID after reopen. Record that
separately from an ordinary app-switcher termination; its native behaviour is
unexecuted until physical hardware is used. Local schema v4 persists the
pre-capture association without replacing the original media/outbox records.

## Return and verify

Return the server `GET /api/trial-build`, baseline/final `GET /live`, the initial empty change page,
immutable `/versions`, paged committed feed JSON, server deploy SHA evidence,
native build/install SHA evidence,
execution receipts, trial message/media receipts, device screenshots and a
redacted `manifest.json`. The manifest keys are `server` (HTTPS), `project_id`,
`baseline_hash`, `baseline_version_id`, `baseline_cursor` (zero),
`baseline_server` (captured `live` and empty `changes` JSON), `server_sha`,
`app_sha`, `final_hash`, `device_a`, `device_b`, `execution` (three objects with
`operation_id`, `activity_uid`, full original `payload`, `local_final_state`,
   `error_code`, `actor_user_id`), and
`communication` (two objects with `id`, `actor_user_id`, `activity_uid`, exact
`text`, `local_final_state`, `error_code`), and `media` with `id`, `actor_user_id`,
`message_id`, `activity_uid`, `original_sha256`, `local_final_state`, `error_code`.
Copy final state/error fields from each device's durable local trial export after
reconciliation; do not derive them from server receipts. The accepted execution
must have `local_final_state=applied`, both accepted notes
`local_final_state=accepted`, and linked media `local_final_state=linked`.
Each successful record must have `error_code` absent, null or an empty string. Device entries need
`model`, `os`, `app_sha`, `actor_user_id`, captured `authority_evidence` (`user_id`),
`offline_evidence`, `termination_evidence`,
`reopen_evidence`, `reconnect_evidence`, `final_cursor`, `final_hash`. The stale two must have
`local_final_state=needs_attention`, `error_code=LIVE_STALE_HEAD`.

Run with a current viewer token stored only in the environment:

```bash
STO_TRIAL_VERIFY_TOKEN=... STO_TRIAL_VERIFY_TOKEN_A=... STO_TRIAL_VERIFY_TOKEN_B=... \
  python3 scripts/verify-pl5-device-trial.py manifest.json
```

The verifier requires exact build SHA equality with its checkout and the
authenticated server build response, the
two distinct authenticated device actors, durable execution/note/media actor
provenance, pinned synthetic fixture activities, arrow/circle/non-empty text
annotation vectors with normalized coordinates,
recorded baseline version/hash in immutable server history and the execution
receipt's base, exactly one accepted execution, both specified notes, exactly
one matching linked media receipt/event and server original-byte digest, no
unrelated committed event, the prescribed execution facts and note text, the
specified accepted operation and committed order, and
both devices' final cursor/hash, and fully reconciled successful local records
with cleared errors. A false manifest can still misstate physical
hardware or installed binary; inspect independent deployment/build and device
evidence before any gate decision. The verifier fails closed on cursor gaps,
missing/duplicate records, stale items lacking attention state, changed
activity links, or a final hash that differs from the accepted execution.
Inspect returned device evidence and lifecycle matrix separately before
deciding PL5/P2-G4. This script does not certify a photo's pixels, genuine
device model, process termination or storage encryption by itself.
The script also cannot prove which person physically held a token or that the
recorded device actually ran the named binary: verify independent installation,
login, and process lifecycle artifacts before a gate decision.
