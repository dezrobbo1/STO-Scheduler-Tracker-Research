# ADR-003: Python core, Java MPXJ sidecar for file interchange

Status: accepted, 2026-09-02

## Context

STO must read `.mpp`, MSPDI, XER and P6 XML and write MSPDI, P6 XML and XER.
Hand-rolling those formats is years of edge cases: three separate hand-rolled
MSPDI parsers already existed across the estate and none read calendars,
relationships and timephased data completely.

`Shutdown-Tracker-Claude` already runs a Java service built on MPXJ 16.4.0 whose
read side uses `UniversalProjectReader` and is therefore already format-agnostic;
the narrowing to `.mpp` and `.xml` sits in its API validation, not the service.
Inspection of the MPXJ jar confirms `UniversalProjectWriter` supports MSPDI,
PMXML, XER, MPX, Planner, SDEF and JSON, and that the readers expose activity
codes, user-defined fields, baselines, raw timephased work and calendar
exceptions. MPXJ cannot write `.mpp`.

## Decision

The core, engine and API are Python. File interchange is delegated to the
existing Java service, ported here as `services/project-worker`, widened to emit
the full canonical document and to write MSPDI, P6 XML and XER. Python speaks to
it over HTTP with the shared-secret header it already implements, and manages its
process lifecycle.

The hand-rolled Python MSPDI importer is retained as an oracle: both paths parse
the same fixtures and their canonical output is diffed. It is deleted once that
cross-check is green on every fixture — which is also the answer to the estate's
four-parsers problem.

## Consequences

One polyglot deployment for one developer, mitigated by the sidecar being
stateless and behind a single client module. In exchange, P6 and `.mpp` support
arrive as configuration rather than as a multi-month parser project, and every
regenerated artifact can be proved by re-reading it with an independent
implementation.

`.mpp` remains readable and not writable. Writing back to a `.mpp`-sourced
schedule is a format conversion and must be labelled as one.
