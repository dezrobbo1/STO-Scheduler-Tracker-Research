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

The hosted disposable API is reachable from the Android emulator through the
standard emulator host bridge. The committed production field configuration
continues to require the hosted HTTPS boundary.

For the CI job only, the runner may adjust its checked-out/generated debug
configuration to permit traffic to the disposable local API. Those temporary
files are not committed and must never be treated as release-network evidence.

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
