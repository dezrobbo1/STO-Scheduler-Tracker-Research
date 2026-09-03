# 2026-09-03 — Calendars compiled, and what the real ones turned out to hold

S2. A canonical calendar becomes sorted integer working intervals over a
horizon; the engine will never again know that a calendar has a base or a
holiday. What was learned doing it:

## The file's calendars are older than its schedule

BOILER has 45 calendars, 14 of them base, 31 inheriting. Eleven carry
exceptions: 40 in the modern form and 65 in the legacy `DayType 0` form the
migration now converts, 105 in all, expanding to 697 dated days. **Every one
of those days falls outside the schedule's window** (2026-08-17 to
2026-09-24): Good Friday 2025, RDOs in December 2024. The calendars were
carried from a template and never re-dated. So the exceptions cannot affect
the 2026 schedule — which is also why the previous engine, which refused any
calendar with an exception inside its horizon, could schedule this file at
all. The exception test compiles over 2025 to exercise them.

## Two exception types, one rule

Type 1 with `Occurrences` and a date range; type 7 with `Period` as well.
Both are "every *period* days, *occurrences* times" — the RDO exception is
seven occurrences every six days across 36 days, and the arithmetic closes.
The compiler treats the two as one family and fails by code on any other
recurrence type until a file shows one.

## A bug the differential found

`earliest_span` was rewritten from the reference's coordinate scan to a
bisect. Ten thousand random trials against the scan found one case the
hand tests had not: a finish bound that equals an interval's start belongs
to that interval, and `bisect_right` skipped it. `bisect_left`; trial 10,000
of 10,000 green. That is what the reference implementation is kept for.

## What was measured against the previous engine

Ten thousand (moment, duration) pairs across all 45 real calendars, the new
indexed arithmetic against the legacy resolver's `_add_working_seconds`:
identical on every pair. The legacy code stays as the oracle it is.

## Scope left where it belongs

Six of the corpus's ten calendar cases pass on the arithmetic alone. The
four that carry relationships — lag on the successor calendar, snapping to
the next interval, SS and negative FS lag — are questions for the forward
pass and are left for it rather than answered with a second, smaller
forward pass inside a calendar test.

Migration gaps paid here: exceptions keep their recurrence instead of being
flattened; special days become exceptions; a missing date or working-time
bound fails the migration instead of being invented.
