# Canonical STO schedule model v0.1

## Status and claim boundary

This is a research schema for deterministic MSPDI import. It is not yet a production scheduling model and makes no Microsoft Project or Primavera P6 semantic-compatibility claim.

The model is intentionally vendor-neutral. Microsoft Project identifiers and unsupported properties are external references or vendor extensions, not canonical primary keys.

## Core document

The canonical document contains:

- `source` — source format, namespace, file hash and non-authoritative document metadata;
- `project` — shutdown/project scheduling context;
- `wbs_nodes` — Microsoft Project summary tasks represented as hierarchy nodes;
- `work_packages` — empty in importer v0.1 because a work package is an operational mapping, not automatically every summary task;
- `activities` — non-summary Project tasks, including milestones;
- `relationships` — explicit FS, SS, FF and SF dependencies with source link codes and lag;
- `calendars` — base/resource calendars, working periods and exceptions;
- `resources` — source resources and groups;
- `assignments` — task/resource links and source work fields;
- `baselines` — source baseline records, currently preserved-only;
- `custom_field_definitions` — MSPDI extended-attribute definitions;
- `vendor_extensions` — unsupported source fields retained as deterministic structured XML payloads;
- `source_inventory` — structural counts and preserved-field diagnostics;
- `compatibility` — explicit import-semantic classification;
- `import_validation` — structural validation outcome.

## Identity model

Canonical identifiers are independent from row descriptions and destination systems.

Examples:

```text
project:{PROJECT-GUID}
task:542
calendar:1
resource:27
assignment:492
relationship:542:0
```

Each entity also carries typed external references such as Project `UID`, row `ID` and `GUID`. Future P6 and EAM identifiers belong in the same external-reference pattern rather than replacing canonical IDs.

## WBS and work packages

MSPDI summary tasks are mapped to `wbs_nodes`. Non-summary tasks are mapped to `activities`. Parentage is reconstructed from source order and `OutlineLevel`, with source `WBS` and `OutlineNumber` retained.

`work_packages` remain separate. A planner may later map one summary branch, several branches or another configured grouping into an operational work package. Import does not assume that every summary task is a work package.

## Time and duration representation

MSPDI date/time strings are retained as source-local strings. Import v0.1 does not invent a timezone or convert them to UTC.

Durations retain:

- the original ISO-8601 text;
- parsed seconds when the value uses the supported fixed-length week/day/time subset;
- a parse status.

Project slack and relationship lag integers are explicitly labelled `*_tenths_minutes_source` or `lag_tenths_minutes`. The raw value is authoritative for interchange; derived lag seconds use the documented tenths-of-a-minute unit.

## Read-only source calculations

These Project-calculated fields are imported as source observations, not accepted as calculations by the new engine:

- early start/finish;
- late start/finish;
- free slack;
- total slack;
- critical flag;
- actual/remaining values during importer v0.1.

A later deterministic comparison phase must calculate supported coordinates independently and compare them with these source observations.

## Vendor extensions

Every unmodelled MSPDI child element is converted into a deterministic namespace-aware object containing its local name, text, attributes and ordered children.

The classification is `Preserved-only`. Preservation means the importer does not silently discard the element. It does not mean the scheduling engine understands, recalculates or can safely write the field back.

Timephased data, Project formulas and many application/UI properties are preserved this way in v0.1.

## Compatibility classifications

Importer v0.1 uses:

- `Full` — identity can be represented directly without known semantic transformation;
- `Mapped` — source data is represented through a declared canonical transformation;
- `Read-only` — source value is retained for comparison but is not recalculated or written;
- `Preserved-only` — retained opaquely without semantic execution;
- `Unsupported` — no claim until a later bounded experiment supplies evidence.

The importer classification is not a destination-system conformance result.

## Validation rules

The custom validator currently enforces:

- schema version and required collection shape;
- unique canonical entity IDs;
- WBS parent existence and absence of parent cycles;
- activity parent references;
- relationship endpoint existence and supported type labels;
- assignment task/resource references;
- project and MSPDI source identity.

Unresolved calendar inheritance is a warning. Missing task/relationship/assignment identities fail the import.

## Phase 1 limitations

Importer v0.1 does not yet:

- calculate a schedule;
- resolve inherited calendar working time into one effective calendar;
- evaluate Project formulas;
- interpret timephased data;
- write MSPDI;
- compare calculated coordinates with Project;
- run Microsoft Project desktop;
- create operational work-package mappings;
- implement field execution, P6, EAM, AI, UI or optimisation features.
