# 2026-09-15 — Real authentication boundary (PL2)

PL2 puts the proven planner behind a server-owned actor boundary. A browser
user signs in with username, Argon2id-protected password and replay-resistant
TOTP, receives an HttpOnly persistent session and uses a session-bound CSRF
value for mutations. Viewer, planner and admin membership is checked by one
dependency on every project route; a non-member receives no project data or
existence disclosure. Project creation and the creator's admin membership
commit atomically.

V005 adds users, memberships, hashed sessions and hashed project-scoped device
tokens. TOTP seeds use authenticated encryption with a required external
master key. Device credentials are displayed once, limited to viewer/planner,
revocable, and capped by their user's live project role. The public liveness
surface is only `/healthz`; detailed application health is authenticated.
Membership grants, role changes and revocations write append-only events;
revocation is project-specific, device credentials are revoked with it, and
the last enabled project administrator cannot be demoted or removed. All
actor-specific API responses are explicitly non-cacheable.

The upgrade regression starts at V004 with a project, immutable import,
baseline calculation and active duration scenario. The supported migration
command applies V005, schema drift reports five migrations and fourteen
application tables, every version/result identifier survives, and the first
administrator sees the old project only after an explicit grant.
Historical actor UUIDs from the previously unconstrained provenance columns
also survive; new writes are foreign-key checked against real users.

The rendered acceptance keeps credentials out of artifacts while proving
logged-out refusal, password+TOTP login, the complete PL14 edit/movement/reset/
export loop, logout refusal, re-login, process restart and recovered scenario
provenance. The P1 authentication gate is executable in
`tests/test_authentication.py`; P1 itself remains open on its two external
Microsoft Project/BOILER evidence criteria.
