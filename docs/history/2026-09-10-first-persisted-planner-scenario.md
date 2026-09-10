# 2026-09-10 — The first persisted planner scenario (PL14)

PL14 closes the first planner loop on the consolidated stack:

1. create or open a project and import MSPDI/XML;
2. calculate and store the immutable baseline;
3. choose a supported, not-started leaf activity;
4. change its planned duration under an expected-version check;
5. calculate and persist a separate scenario version and result;
6. compare imported, baseline and scenario spans in the table and Gantt;
7. reset the active head to baseline, repeat the edit, restart and recover it;
8. download a labelled prototype-state JSON export.

The edit is deliberately one field and one activity. `V004` records the old
and new integer seconds beside the source baseline and scenario version,
including the synchronised remaining-duration mirror when one existed. The
database makes that change row append-only and validates its lineage. The
candidate calculation runs before the transaction; publication then writes
the canonical version, lineage, result rows and scenario head together after
rechecking the current baseline and active planner version. A stale request
writes none of them.

The page does not make evidence boundaries disappear. Each activity says
whether it was calculated normally, calculated with an assumption, carries a
deferred constraint, or was excluded. Source dates remain observations. The
baseline and scenario results retain separate fingerprints and never overwrite
one another.

`tests/test_planner_scenario.py` exercises baseline immutability, edit
validation, stale conflicts, downstream movement, WBS/result persistence,
project isolation, reset, re-import, restart reconstruction and export against
PostgreSQL. `tests/test_calculation_page.py` executes the rendered movement and
disposition classifier. `scripts/browser-acceptance-pl14.py` drives Chromium
through the complete synthetic practitioner workflow, including an actual
application-process restart, and writes screenshots and the downloaded export
to the CI evidence artifact.

One available real shutdown fixture is also run locally through the current
production engine with a supported, assumption-free activity selected by
structure. Its file remains outside the repository, and only the aggregate
movement result is reported.

The KILN evidence fixture (SHA-256
`b7c14b631ecc7c15db7731e4a5159ecefe68aaa1c10e76262f84db6b8c37d3ca`)
was also used for one bounded local smoke check. An assumption-free supported
activity was lengthened and the production engine moved its successor spans.
This is an INTERNAL CONFORMANCE scenario probe over real input, not a pinned
agreement measurement, stored-XML agreement or Project-native result.

This is a scenario-state export, not Microsoft Project round-trip evidence.
No Project-native session is part of PL14.
