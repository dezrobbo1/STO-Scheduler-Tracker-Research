# P1 gate review correction — 2026-09-21

## Decision

P1-G2 is reopened and P1 returns to `in_progress` at 4/5. P1-G3 remains met:
the clean controlled Microsoft Project repeat changed 43 contract fields, all
43 match the independently predicted engine transition, and there are zero
unexpected transition differences. P2 remains `not_started` and is no longer
the current phase.

## Why the earlier closure was wrong

The field classifier called a value `UNCHANGED` when the engine prediction and
native observation both stayed still. It did not require the engine's static
value to equal the observed source value. That let pre-existing engine/source
disagreements pass through the full-leaf P1-G2 check.

The corrected classifier requires baseline and recalculated equality before
using `UNCHANGED`. Otherwise it records `BASELINE_MISMATCH`, includes the field
in the full-parity failure count, and keeps it separate from unexpected native
transition changes. On the verified clean repeat this produces:

- 3,594 exact unchanged fields;
- 422 static baseline mismatches across 105 leaf identities;
- 43 exact engine/native transition agreements;
- 81 fields belonging to nine coded exclusions; and
- zero unexplained changed fields.

The static mismatches comprise 62 Start, 67 Finish, 62 Early Start, 67 Early
Finish, 42 Late Start, 33 Late Finish, 71 Total Float, 16 Free Float and 2
Critical fields.

## Related review corrections

The same bounded correction set also:

- persists the backward pass's late remaining-start coordinate separately from
  public `LateStart`, so an in-progress negative-float span remains valid at the
  database boundary;
- evaluates the measured in-progress predecessor/successor shape only after
  excluded relationship endpoints have been removed; and
- adds regressions for the classifier, retained-network assumption boundary,
  result fingerprint, migration constraint and stored-result round trip.

The earlier 2026-09-20 closure record is retained for audit history and marked
as superseded rather than rewritten as if the incorrect decision never
occurred.

## Verification

Both controlled native tests passed with the hash-guarded external baseline and
Project outputs present. The complete suite passed 859 tests with the verified
BOILER, KILN, CALCINER, untouched-source and both controlled native files
present; 103 database, unavailable day-five/native-completion and environment
dependent cases skipped under their declared gates. Compileall, JSON parsing,
migration checksums, roadmap rendering/status and whitespace checks also
passed. The PostgreSQL persistence and upgrade cases remain mandatory in the
PR's database CI job because this local environment has no PostgreSQL server.
