# Prototype 0 — local schedule workspace

Prototype 0 turns the existing MSPDI importer and bounded forward scheduler into a local, inspectable product slice.

## Start it

From the repository root with Python 3.11 or newer:

```bash
python -m pip install -e .
python -m sto_scheduler_core workspace
```

The command serves the workspace only on the local loopback interface and opens `http://127.0.0.1:8765/` in the default browser. Stop it with `Ctrl+C` in the terminal. Pass `--no-open` if the browser should not open automatically.

## Use it

1. Import a Microsoft Project XML/MSPDI file.
2. Browse or search the complete imported hierarchy.
3. Compare the muted imported Gantt bar with the stronger calculated bar.
4. Select a non-milestone activity labelled **Calculated**.
5. Enter a duration in hours and choose **Recalculate schedule**.
6. Review the moved-task view. Dashed bars show the pre-scenario calculated dates; solid bars show the current dates.
7. Choose **Reset scenario** to restore the original calculation, or **Export JSON** to download the current prototype state.

The JSON artifact is a workspace-state export. It is not an MSPDI export and cannot be opened as a Microsoft Project schedule.

## Calculation boundary

The workspace calculates only the activities admitted by calculation profile `mspdi-calculation-eligibility-v0.2`. The current supported subset is:

- schedule from project start;
- automatically scheduled, active, not-started activities;
- ASAP constraints;
- hour-format durations with internally consistent duration, work and assignment facts;
- FS relationships with zero lag; and
- the bounded negative elapsed-day FS-lead case already implemented by Phase 1.3.

Summary tasks and excluded activities retain their imported dates and are view-only. The workspace does not calculate backward-pass dates, float, progress, resource levelling, SS/FF/SF links, positive lag, or calendar exceptions inside the calculation horizon.

Scenario duration changes are applied to a copied engine projection. The canonical import, source duration and imported start/finish values remain unchanged. A conservative guard rejects a change if a moved activity would leave the imported calculation horizon after its calendar exceptions were excluded as out-of-horizon.

Prototype 0 keeps one active duration override. Applying a change to another task replaces the previous override and recalculates again from the unchanged base projection.

## Real-source trial

The recommended external acceptance input is the supplied Boiler MSPDI XML with SHA-256:

```text
e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420
```

In the Prototype 0 acceptance run it imports 555 tasks, displays 95 summaries and 460 leaf activities, and calculates 282 activities connected by 327 eligible relationships. The real XML and any full source-derived output must remain outside this public repository.

For a visible trial, use the upstream activity suggested in the duration panel and increase its duration. The moved-task view should then show the activities whose calculated coordinates changed. This does not imply that the imported dates or the overall project finish move.
