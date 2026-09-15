# ADR-015: Close the PL2 authentication boundary after merge

Status: accepted, 2026-09-16

## Context

The post-merge review of PL2 found five bounded gaps around an otherwise valid
authentication boundary: the browser reported logout success after an
unconfirmed request; disabling a user could leave a project without an enabled
administrator; enrollment accepted inputs the login schema refused; scenario
reset moved a persisted head without an attributed event; and the detailed
health route handled failure of its first database probe but not its second,
actor-filtered read.

These are authentication, persistence and explanation defects. They do not
change scheduling semantics and do not begin the Phase 2 execution-event
model.

## Decision

Browser logout has three outcomes: confirmed revocation, an already-invalid
session, and unconfirmed revocation. Every outcome immediately removes planner
content from the page. Only the first is described as server revocation. An
unconfirmed outcome exposes a retry action which first obtains the current
session-bound CSRF value and then retries the protected mutation; no credential
or token is stored in browser storage. Sign-in controls remain disabled until
the retry reaches a confirmed outcome. If another client signs in instead, issuing
the replacement session and revoking the session token currently in the cookie
commit atomically, so overwriting the cookie cannot orphan a live session.

User disable, membership grant, demotion and revocation share a short
transaction advisory lock. Disabling an account locks its administrative
projects in stable order and refuses if any would be left without an enabled
administrator. There is no ordinary or silent emergency bypass: another
enabled administrator must be granted or the memberships deliberately
reassigned first. An accepted disable revokes browser sessions and device
tokens in the same transaction. Credential revocation uses a post-wait clock
value bounded below by its issuance time, so a disable that waited behind
concurrent issuance cannot violate the persisted timestamp invariant.

Enrollment and login share one username/password boundary: usernames are 1 to
200 input characters and must remain non-blank after NFKC normalization,
passwords are 12 to 1024 characters. Enrollment validates before hashing,
persisting or generating TOTP enrollment material.

V006 adds `scenario_reset_events`. A real scenario-to-baseline reset records
the authenticated actor, project, prior scenario, restored baseline and time
in the same transaction that removes the scenario head. The table is
append-only against update, delete and truncate and database-validated for
same-project lineage. A stale refusal
records no event; an already-baseline request returns an explicit no-op receipt
and records no reset. Immutable schedule versions and calculations remain.

The authenticated detailed-health route handles both its database probe and
actor-visible project query inside the same controlled response boundary. It
returns only a degraded status and exception type on failure. The separate
healthz route remains the sole public, minimal liveness endpoint.

## Consequences

The V005-to-V006 upgrade adds audit state without changing existing projects,
versions, calculations, authentication records or scenario results. The PL14
workflow remains the same, with a richer reset receipt. P1 remains open on the
two external Microsoft Project/BOILER evidence criteria; this decision neither
claims nor changes them.
