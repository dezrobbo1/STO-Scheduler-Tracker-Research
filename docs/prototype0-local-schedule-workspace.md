# Prototype 0 — local schedule workspace

## Purpose

Prototype 0 turns the existing importer and bounded forward scheduler into the first inspectable product slice:

```text
MSPDI XML -> canonical import -> complete hierarchy view
                              -> eligible engine projection -> local duration scenario
```

It is intentionally one local desktop-oriented workspace. It does not add authentication, collaboration, execution tracking, recovery optimisation, a backend database or Microsoft Project export.

## Start the workspace

From the repository root with Python 3.11 or later:

```bash
python -m pip install -e .
sto-scheduler-core workspace
```

The command prints the local URL and normally opens it in the default browser. It always binds to `127.0.0.1`; it is not exposed to the network.

Options:

```bash
sto-scheduler-core workspace path/to/source.xml
sto-scheduler-core workspace --port 9000 --no-browser
```

## User flow

1. Import a Microsoft Project XML/MSPDI file.
2. Inspect all summary and activity rows in source order.
3. Compare `Imported start/finish` with `Calculated start/finish`.
4. Use the hierarchy controls, task search and `All`, `Calculated` or `Changed` filters to navigate a full shutdown.
5. Select a row. An excluded activity explains its primary stable reason code. A summary or milestone remains read-only.
6. For a calculated non-milestone activity, enter whole hours, minutes and seconds and choose **Apply & recalculate**.
7. Inspect the changed duration, recalculated dates, date delta and amber Gantt bars for the edited and downstream activities that actually moved.
8. Choose **Reset scenario** to restore import-time calculated dates while keeping the imported file open.
9. Choose **Export JSON** to download the current prototype view and scenario provenance.

## State and calculation boundary

The local process holds these layers:

| Layer | Mutability | Purpose |
| --- | --- | --- |
| Canonical MSPDI import | Immutable | Complete source hierarchy, observations and preserved fields |
| Eligibility profile | Immutable | Exact activity and relationship cohort admitted by calculation profile v0.2 |
| Base engine projection/calculation | Immutable | Import-time engine-native dates for the admitted subset |
| Duration overrides | Mutable | Explicit scenario values for selected eligible non-milestones |
| Current calculation | Derived | Fresh forward pass over a copy of the base projection |

The application does not overwrite canonical activity duration. Doing so would conflate a scenario with the imported source and invalidate the existing eligibility checks against source spans and remaining values.

Every edit and reset request includes the imported `source.document_key` and the displayed scenario revision. This prevents a document-local task identifier such as `task:2` from being applied after a different schedule has replaced the current import, and rejects stale-tab mutations.

The current calendar projection contains weekly patterns only. Before publishing base or scenario dates, the workspace checks each non-milestone's effective dependency-candidate-to-finish window, including negative-lag candidates, against ignored exceptions and special days on every relevant task/resource calendar lineage. An unsafe base falls back to imported-only display; an unsafe override is rejected transactionally rather than calculating through a known boundary.

## Display contract

- Every summary and leaf activity remains in the table.
- Summary dates are source observations only; summary calculated fields are `null`.
- Excluded activity dates are source observations only; excluded calculated fields are `null`.
- If the bounded profile cannot be built, the complete imported hierarchy remains available and all calculated fields stay `null`.
- Eligible activity calculated dates are engine-native bounded forward dates.
- The Gantt envelope is derived from task date extrema, not the Project header, because source tasks may fall outside the header span.
- Amber highlighting means the current engine calculation differs from the import-time engine calculation. It does not mean Microsoft Project has been changed.
- Dates are displayed as timezone-naive schedule-local strings, matching the current canonical import boundary.

## JSON export

The download is labelled:

```text
prototype-0-local-schedule-workspace-state
```

It contains the thin task view, imported source provenance, current overrides, scenario counts and hashes for the base projection, base calculation and current calculation. The browser builds the file directly from the state currently displayed in that tab, so a concurrent tab cannot substitute another schedule during download. It is an inspectable Prototype 0 state export, not an MSPDI export, Project write-back file, durable persistence format or JSON re-import contract.

## Local API boundary

The standard-library HTTP server exposes only:

- `GET /api/workspace`
- `POST /api/import`
- `POST /api/scenario/recalculate`
- `POST /api/scenario/reset`

Imports are capped at 32 MiB. Host and mutation-origin checks reject non-local browser requests. The browser receives a thin task view rather than the full canonical document and its preserved vendor extensions. Only an activity identifier, document key, scenario revision and integer duration seconds are accepted for recalculation; the browser cannot submit calendars, relationships or an engine projection.

## Automated acceptance fixture

`tests/fixtures/prototype0-chain.mspdi.xml` is wholly synthetic. It contains two summary rows and a three-activity FS chain on a weekday calendar. The tests prove:

- complete hierarchy import;
- imported and calculated date coexistence;
- an eight-hour duration override on the first four-hour activity;
- movement of that activity and its two downstream activities;
- immutable imported duration;
- exact reset to the base calculation;
- current-state JSON export;
- stale document identity, unsupported activity, milestone and invalid-duration rejection;
- transactional rejection when a scenario crosses an ignored calendar exception;
- imported-only fallback when project calculation coordinates are unavailable;
- the HTTP import/recalculate/reset flow and local security headers.

Run all tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## External Boiler acceptance boundary

The real Boiler MSPDI remains outside this public repository. Its recorded source hash and Phase 1 evidence can be used to confirm that the current importer/profile still produce 555 total tasks, 95 summaries, 460 leaf activities, 282 eligible activities and 327 eligible relationships before a local browser trial. Do not commit the source XML, full canonical output, scenario JSON, screenshots or logs containing source names and WBS data.

## Explicit limitations

Prototype 0 does not provide:

- calculated summary rollups;
- backward pass, late dates, float or critical-path results;
- positive lag, non-elapsed lag or SS/FF/SF calculation;
- progress/status-date calculation;
- resource levelling;
- multiple-user persistence, approval or audit workflow;
- MSPDI export or Microsoft Project write-back;
- native Microsoft Project recalculation evidence;
- a production scheduling engine.

The current claim remains: deterministic engine-native forward dates for the declared eligible subset only.
