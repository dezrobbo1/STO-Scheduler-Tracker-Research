# Post-merge importer hardening v0.1.1

Related issue: #5

## Reason

PR #4 merged after Codex review capacity was exhausted. A direct review of `main` found a usable structural importer, but also found several bounded defects and a mismatch between an earlier progress report and the code that actually merged.

The merged repository contained:

- the structural MSPDI importer;
- deterministic canonical serialization and hashing;
- structural validation;
- the synthetic importer tests;
- historical sanitized Boiler import evidence.

It did not contain the previously described comparison eligibility profile or deterministic reference scheduling engine.

## Corrections in v0.1.1

- Preserve summary-task milestone state in canonical WBS nodes.
- Reject unresolved non-negative assignment `ResourceUID` values.
- Reject missing, negative or malformed outline hierarchy.
- Independently validate outline parent level and source ordering.
- Record that canonical entity references are document-local in v0.1.1.
- Record a source-derived `document_key` and defer durable cross-snapshot identity explicitly.
- Define `VendorExtension` as normalized structured retention, not lossless XML preservation.
- Keep the original MSPDI as the preservation authority.
- Exercise the current checked-in JSON Schema top-level/source contract in CI without adding a runtime dependency.
- Preserve the historical v0.1.0 schema unchanged as evidence for importer v0.1.
- Add regression tests for all review findings.
- Correct README and Phase 1 scope records.

## Compatibility treatment

The historical schema at `schemas/canonical-schedule-v0.1.schema.json` remains the original `0.1.0` contract used by importer profile `mspdi-import-v0.1` and its committed Boiler evidence.

The hardened importer emits canonical schema version `0.1.1` and importer profile `mspdi-import-v0.1.1`, described by `schemas/canonical-schedule-v0.1.1.schema.json`. The schema version advances because v0.1.1 adds explicit source identity requirements and summary-milestone state that were not part of the v0.1.0 contract.

The custom validator targets the current `0.1.1` document contract. Historical v0.1.0 evidence remains reproducible through its preserved schema rather than by rewriting the old schema path into the new contract.

The package version also advances to `0.1.1` because parsing and validation are deliberately stricter.

## Boundary

This hardening PR does not add:

- schedule calculation;
- a comparison eligibility profile;
- MSPDI export;
- Microsoft Project desktop execution;
- a Project/P6 compatibility claim;
- P6, EAM, AI or UI work.

## External source evidence

The committed Boiler result remains labelled as historical evidence for importer profile `mspdi-import-v0.1` and canonical schema `0.1.0`. Importer v0.1.1 changes canonical output intentionally. A new external Boiler hash must therefore be recorded as a separately labelled evidence run after this hardening slice is reviewed.
