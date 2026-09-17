# 2026-09-16 — PL2 post-merge closure

The bounded review closure corrected five findings without changing scheduler
behavior. Logout now distinguishes confirmed revocation, an already-invalid
session and an unconfirmed network/HTTP failure; planner content is always
cleared and an unconfirmed session can be revoked through a fresh-CSRF retry.
Account disabling now shares the membership authority lock, refuses to remove
the last enabled administrator, and atomically revokes sessions and device
tokens when accepted. Enrollment and login enforce the same normalized
username and password limits before any hashing or TOTP material is produced.

V006 adds an append-only, actor-attributed event for a real PL14 scenario reset.
The event and scenario-head movement commit together; stale requests and
already-baseline no-ops do not claim a reset, while immutable scenario versions
and results remain available. Detailed authenticated health also degrades
cleanly if either the probe or the actor-filtered visibility read fails, without
exposing another project or connection detail.

The migration regression starts with the complete V005 authenticated planner
state, applies V006 through the supported migrator, reconstructs the workspace,
and proves that the preserved scenario can be reset and audited. P1 remains at
three of five criteria: the exact progressed/day-5 BOILER fixture is not
available, and the native Project comparison still needs execution plus an
unexpected-difference classifier for its changed common rows.
