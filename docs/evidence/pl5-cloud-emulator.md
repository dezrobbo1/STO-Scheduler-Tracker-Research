# PL5 cloud Android emulator gate

This workflow is a disposable engineering shakeout for the PL5 field shell. It
does **not** replace the genuine-device return in
`docs/evidence/pl5-device-return.md` and it cannot close P2-G4.

## Scope

The cloud gate is intended to let Work converge Android behaviour without the
owner's desktop. A GitHub-hosted Linux runner creates a disposable PostgreSQL
database, builds the exact PR-head Capacitor app, boots an Android emulator,
installs the app, and exercises the native SQLite-backed field workflow.

The disposable environment must remain separate from the prepared genuine
device project and its device tokens.

The gate covers, where the emulator/runtime supports them:

- exact PR-head Android build and install;
- native SQLite/SQLCipher store startup;
- online connection and baseline cache;
- server-unavailable queueing;
- force-stop and offline reopen;
- reconnect and durable reconciliation;
- local account A to account B handover;
- online deep-link selection;
- retained deep link applied after a later confirmed sync;
- screenshots, logcat, package metadata, server logs and safe local evidence.

It does not claim:

- physical Android hardware;
- physical camera behaviour or Android OS camera-process reclamation;
- mobile radio or Wi-Fi/cellular transition evidence;
- physical-device storage characteristics;
- final PL5 or P2-G4 acceptance.

## Disposable authority

CI creates an ephemeral project, users and project-scoped device credentials in
the runner's disposable PostgreSQL database. They are not Railway credentials
and they are not the genuine trial credentials.

Secret credential values stay in runner-private temporary files, are masked
before command output, and are never uploaded as artifacts. Uploaded evidence
contains only safe identifiers, hashes, states and receipts.

## CI-only networking

The disposable API is reachable from the Android emulator through its standard
host-bridge address. The literal CI-only address is kept in executable test
infrastructure rather than documentation.

The production field boundary requires HTTPS, so the cloud gate does not weaken
the JavaScript identity check to accept HTTP. Instead each CI run creates an
ephemeral certificate authority and a one-run server certificate for the
emulator host bridge. The debug Android variant receives that CA as a temporary
debug-only trust anchor through files created in the runner workspace after
checkout.

The CA private key, server key and generated debug trust files are runner-only.
They are not committed or uploaded as evidence. The ordinary production
Capacitor configuration and HTTPS requirement remain unchanged.

The resulting emulator APK is therefore a CI debug shakeout build, not the
physical-device release candidate. The final return still requires the exact
unmodified source/server SHA and independent native install provenance on
physical iOS and Android hardware against the hosted HTTPS backend.

## Autonomous Work convergence

A cloud Work task can use the gate as a deterministic convergence oracle:

```text
PR head
  -> ordinary CI
  -> PL5 cloud Android emulator job
  -> inspect failing phase, logs and artifacts
  -> reproduce a repository defect
  -> make the smallest bounded correction on the same Draft PR
  -> wait for CI
  -> repeat
```

A runner/emulator infrastructure failure must be classified separately from a
product defect. Work must stop before changing physical-device acceptance
requirements, exposing credentials, marking the PR ready, or merging it.

## Cloud mobile convergence correction

The Android path filter includes locked Python dependencies, all STO server
modules (including the fixture importer), migrations/database scripts, the
synthetic fixture, field app/native tests and the harness/evidence scripts.
Unrelated documentation does not trigger the emulator gate.

Native bridge argument logging is disabled: debug bridge output previously
included disposable tokens and the SQLite passphrase. Evidence is collected
outside the upload directory, redacted, scanned and published only through the
safe finalizer. The cloud workflow retires earlier same-branch emulator
artifacts with raw debug logs, pinned by their audited artifact IDs; it cannot
delete future safe evidence or physical return artifacts.

Queue/reopen/reconciliation evidence now binds immutable UUIDs and frozen
execution/note facts, original media digest and annotation vectors, final
local states, server receipts, actor provenance and final cursor/hash. Account
B must have no A local execution, note or media records. The server stays
unavailable for the retained-link assertion and restarts only after a native
test readiness signal; a fixed delay cannot race simulator startup.

### Synthetic media

Android instrumentation supplies a generated PNG to the real production file
input, invokes its change handler, and uses the actual annotation controls and
canvas pointer events for arrow, circle and nonempty text. It queues through
production handlers into native SQLite, survives force-stop/offline reopen,
and reconciles original upload and media link to the disposable API. This
proves the application path after file selection, not the OS picker or camera.
Real camera, OS camera reclamation and interrupted transfer remain physical
acceptance requirements.

### Reboot

REBOOT — DEFERRED TO PHYSICAL DEVICE. The cloud gate retains force-stop and
offline process reopen. It already tests durable cache/identity and outbox
recovery; reboot adds runner boot variability without proving physical secure
storage behaviour. The physical lifecycle matrix still requires reboot.

### iOS startup

The separate macOS job in ordinary CI selects an available iPhone runtime,
builds the committed App project without distribution signing and verifies
bundle identity/version/build. Runner-only Vision OCR polls the actual
simulator screenshot for the rendered connection form. That form starts
hidden and is shown only after the production encrypted database and
FieldStore migrations/active identity read finish. The job also checks that
the native database exists and has an encrypted header, without exporting it.
It retains a source-bound startup result, screenshot, install/launch/process
identity, Xcode/runtime details and sanitized bounded logs. This is a native
startup smoke, not the deeper Android behavioural oracle or physical evidence.

The rendered startup check exposed the missing iOS SQLite keychain namespace:
setting the encryption secret failed before the local store could open. The
configuration now pins the app-specific prefix to the bundle identifier; no
signing credential or encryption key is committed. Keep this prefix stable for
future upgrades. The old compilation/launch-only success did not establish
native storage readiness.

The simulator build uses a local ad-hoc signature (`CODE_SIGN_IDENTITY=-`),
without certificates, provisioning profiles or Apple credentials. Removing all
signing allowed launch but denied the production Keychain secret write. The
gate captures/verifies the simulator signature and requires native encrypted
startup; it does not bypass Keychain or weaken physical signing requirements.

Media feed events have no actor field: provenance is bound through the durable
upload receipt plus link UUID/sequence/project. Server annotation receipts
normalize optional absent fields to null; the verifier compares non-null facts
and still rejects altered coordinates, text, digest, owner or link identity.
