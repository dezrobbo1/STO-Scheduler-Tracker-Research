# ADR-014: Real authentication and project authority at the API edge

Status: accepted, 2026-09-15

## Context

PL14 proved the persisted planner workflow, but every FastAPI route trusted an
anonymous caller. That was sufficient for a loopback prototype and is not a
boundary for a controlled multi-user trial. Identity cannot be a request
header, a default account or a browser-local value: those would leave the
database and scheduling routes unable to distinguish an actor from a claim.

Authentication also cannot enter `sto.core`. The engine and canonical hashing
remain stdlib-only under ADR-005; identity is an API and persistence concern.

## Decision

V005 adds five tables. `users` stores normalized unique usernames, Argon2id
password hashes, encrypted TOTP seeds, the last consumed TOTP counter and the
enabled state. `project_memberships` is the authoritative project/actor role
mapping; project-specific revocation is explicit and the last enabled project
administrator cannot be demoted or removed. `project_membership_events`
retains every grant, role change and revocation in an append-only,
database-guarded history. `server_sessions` and `device_tokens` store only
keyed SHA-256 hashes
of high-entropy tokens plus independently random display prefixes. Foreign
keys bind a device token to an existing user/project membership. Existing
V004 projects and versions gain no implicit membership during migration.
The actor columns created before a users table existed retain any historical
UUID values: their new foreign keys are installed `NOT VALID`, so PostgreSQL
checks every future insert/update without rejecting an otherwise sound upgrade
because an old attribution has no authentication record.

Passwords use `argon2-cffi` Argon2id with a 64 MiB memory cost, three
iterations, four lanes, a 32-byte hash and 16-byte random salt. Login performs
transparent rehash when those parameters change. TOTP uses `pyotp`'s RFC 6238
six-digit, 30-second code with a one-step clock window. The candidate is
verified without holding a database lock; a short row lock atomically compares
and advances the consumed counter, so the same or an older code cannot be
replayed.

The TOTP seed is encrypted with Fernet authenticated encryption. Its master
key comes from `STO_AUTH_MASTER_KEY` and never enters git or the database. The
API fails closed at construction if the key is absent or invalid. A local,
interactive `sto auth bootstrap-admin` command creates the first user only
while no user exists, reads the password with `getpass`, and displays TOTP
enrolment material once. It does not grant existing project access. Further
bounded commands create a user, grant one project role or disable a user.

A browser login creates a persistent, revocable server-side session. The raw
token exists only in an `HttpOnly`, `SameSite=Strict` cookie with explicit
expiry (eight hours by default). `Secure` is controlled by
`STO_COOKIE_SECURE` and is required for a TLS/public deployment. The
authenticated session response returns an HMAC-derived CSRF value bound to
that session. The page keeps it in memory and every cookie-authenticated
mutation must return it in `X-CSRF-Token`. Device bearer requests do not use
cookie CSRF semantics.

Project roles are only `viewer`, `planner` and `admin`. Viewers read persisted
planner state. Planners also import, calculate and create/reset the bounded
duration scenario. Admins also manage membership and issue/revoke device
tokens. Device tokens are project-scoped, limited to `viewer` or `planner`,
and capped by the current membership of their user; they can never administer
memberships or credentials. A disabled user cannot be issued a credential, and
revoking their project membership also permanently revokes its device tokens.

All project routes use one `require_project_role` dependency. Absence of
membership and a token used against another project both return 404. The
project list is produced by a membership join. A route-table regression fails
if a future application route lacks the central authenticated or
project-scoped dependency. GET /healthz is the sole public operational route and
contains only `{status: ok}`; the detailed GET /api/health response is protected
and filtered to projects visible to the actor. The unused FastAPI OpenAPI and
interactive documentation routes are disabled in the trial deployment. Every
application API response is marked `private, no-store` and varies on cookie and
authorization, so an actor-filtered response cannot cross a shared cache.

## Consequences

The same immutable import, expected-version check, scenario calculation,
reset, restart and export paths now carry an authenticated actor at their
persistence edge. No scheduling semantics changed. Sessions and device
revocations survive a process restart, while disabling a user immediately
invalidates both credential types.

This is a controlled-trial identity boundary, not enterprise identity
management. Password recovery, SSO, social login, distributed session stores,
login-rate policy and Phase 2 execution workflows remain outside PL2.
