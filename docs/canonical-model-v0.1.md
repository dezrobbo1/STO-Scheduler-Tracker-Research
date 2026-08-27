# Canonical STO schedule model v0.1

## Status and claim boundary

This is a research schema for deterministic MSPDI import. It is not a production scheduling model and makes no Microsoft Project or Primavera P6 semantic-compatibility claim.

The model is intended to become vendor-neutral, but importer v0.1 still uses document-local canonical references derived from Microsoft Project UIDs. That boundary is explicit below and must be replaced or wrapped before multi-project persistence or cross-snapshot reconciliation.

## Core document

The canonical document contains:

- `source` — source format, namespace, source hash, document identity scope and non-authoritative document metadata;
- `project` — shutdown/project scheduling context;
- `wbs_nodes` — Microsoft Project summary tasks represented as hierarchy nodes, including retained summary-milestone state;
- `work_packages` — empty in importer v0.1 because a work package is an operational mapping, not automatically every summary task;
- `activities` — non-summary Project tasks, including milestones;
- `relationships` — explicit FS, SS, FF and SF dependencies with source link codes and lag;
- `calendars` — base/resource calendars, working periods and exceptions;
- `resources` — source resources and groups;
- `assignments` — task/resource links and source work fields;
- `baselines` — source baseline records, currently preserved-only;
- `custom_field_definitions` — MSPDI extended-attribute definitions;
- `vendor_extensions` — normalized structured representations of selected unsupported source elements;
- `source_inventory` — structural counts and retained-field diagnostics;
- `compatibility` — explicit import-semantic classification and identity/preservation boundaries;
- `import_validation` — structural validation outcome.

## Identity model

Examples of importer v0.1 entity references are:

```text
project:{PROJECT-GUID}
task:542
calendar:1
resource:27
assignment:492
relationship:542:0
```

These IDs are deterministic within one imported source document, but task, calendar, resource, assignment and relationship IDs are **document-local**, not globally durable identities. They can collide with IDs from another Project file or another snapshot.

The source block therefore records:

```text
identity_scope = document-local-v0.1
document_key = sha256:{SOURCE_FILE_HASH}
durable_cross_snapshot_identity = not_implemented
```

Any consumer combining documents must scope entity references by `source.document_key`. A later canonical model must introduce application-owned durable identities and reconciliation rules while keeping Project UID, ID and GUID as typed external references.

## WBS and work packages

MSPDI summary tasks are mapped to `wbs_nodes`. Non-summary tasks are mapped to `activities`. Parentage is reconstructed from source order and `OutlineLevel`, with source `WBS` and `OutlineNumber` retained.

Importer v0.1.1 fails closed when an outline level is missing, negative, jumps past a required summary parent, or points above the document root. The independent canonical validator also checks parent level and source ordering.

`work_packages` remain separate. A planner may later map one summary branch, several branches or another configured grouping into an operational work package. Import does not assume that every summary task is a work package.

## Time and duration representation

MSPDI date/time strings are retained as source-local strings. Importer v0.1 does not invent a timezone or convert them to UTC.

Durations retain:

- the original ISO-8601 text;
- parsed seconds when the value uses the supported fixed-length week/day/time subset;
- a parse status.

Project slack and relationship lag integers are explicitly labelled `*_tenths_minutes_source` or `lag_tenths_minutes`. The raw value is authoritative for interchange; derived lag seconds use the documented tenths-of-a-minute unit.

## Read-only source calculations

These Project-calculated fields are imported as source observations, not accepted as calculations by a new engine:

- early start/finish;
- late start/finish;
- free slack;
- total slack;
- critical flag;
- actual/remaining values during importer v0.1.

A later deterministic comparison phase must calculate supported coordinates independently and compare them with these source observations.

## Structured retention boundary

`VendorExtension` records retain a deterministic, namespace-aware, normalized object containing element name, selected namespace, trimmed text, attributes and ordered children at declared import locations.

This is **not byte-for-byte or lossless XML preservation**. The normalization does not retain every XML serialization detail, whitespace distinction, namespace-prefix choice or tail-text distinction, and not every interpreted source subtree is duplicated as opaque XML.

Therefore:

- `Preserved-only` means structured source information is retained for inspection at a declared location;
- it does not mean the importer can regenerate semantically or byte-identical MSPDI;
- it does not prove safe Project round trip;
- the original MSPDI XML remains the source-preservation authority.

Timephased data, Project formulas and many application/UI properties are retained this way in v0.1.

## Assignment resource references

An assignment with a non-negative `ResourceUID` must resolve to a resource in the imported resource table. Importer v0.1.1 rejects unresolved identifiers rather than inventing `external-resource:<uid>` records. Negative source values may represent an explicit null/unassigned reference and map to `null`.

A genuine external-resource model may be added only through a later bounded experiment with explicit source semantics.

## Compatibility classifications

Importer v0.1 uses:

- `Full` — identity can be represented directly without known semantic transformation within the declared document-local boundary;
- `Mapped` — source data is represented through a declared canonical transformation;
- `Read-only` — source value is retained for comparison but is not recalculated or written;
- `Preserved-only` — retained as normalized structured source information without semantic execution;
- `Unsupported` — no claim until a later bounded experiment supplies evidence.

The importer classification is not a destination-system conformance result.

## Validation rules

The custom validator currently enforces:

- schema version and required collection shape;
- unique canonical entity IDs;
- WBS parent existence and absence of parent cycles;
- coherent outline levels, expected summary parents and parent-before-child ordering;
- activity parent references;
- relationship endpoint existence and supported type labels;
- assignment task and resource references;
- summary milestone state when supplied;
- project and MSPDI source identity;
- document-local identity scope and source-derived document key for importer v0.1.1.

Unresolved calendar inheritance remains a warning because calendar inheritance has not yet been executed by the scheduler.

The checked-in JSON Schema is also exercised in CI by a standard-library contract test that compares its required top-level/source boundary with importer output. This is not a full Draft 2020-12 runtime evaluator; semantic and reference validation remains the responsibility of the custom validator.

## Phase 1 limitations

Importer v0.1 does not yet:

- calculate a schedule;
- resolve inherited calendar working time into one effective calendar;
- evaluate Project formulas;
- interpret timephased data;
- provide lossless MSPDI shadow preservation;
- write MSPDI;
- compare calculated coordinates with Project;
- run Microsoft Project desktop;
- provide durable cross-snapshot identities;
- create operational work-package mappings;
- implement field execution, P6, EAM, AI, UI or optimisation features.
