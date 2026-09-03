# ADR-005: One dependency-free base package, third-party code behind an extra

Status: accepted, 2026-09-03

## Context

`pyproject.toml` declares no dependencies, `sto.core` is stdlib-only under
`PR-core-stdlib-only`, and the whole suite runs on a bare `python3` with nothing
installed. That is not an accident of youth: it is why canonical hashing can be
tested without a database and why no validation library can reorder a field and
move a hash.

The next slice needs a web framework, a database driver and a schema library.
The consolidation design answers this with `uv` managing one dependency set and
`uv sync --frozen` in redeploy — but `uv` is not installed on this machine, and
a single dependency set would end the property above: the suite would stop
running on a bare interpreter and CI would gain an install step in front of
every test.

## Decision

The base package keeps `dependencies = []`. Everything the API needs —
framework, server, driver, schema library — goes behind an optional `api`
extra with a lockfile, installed by `uv`, which is now on this machine.

The division is the one already drawn: `sto.core` and the importer are
stdlib-only and enforced; the API, persistence and CLI layers may use the extra.
CI keeps running the suite with nothing installed, and adds a job that installs
the extra once the code under it exists.

## Consequences

Two claims survive that a single dependency set would have cost: the engine is
testable on any machine with a Python interpreter, and a hash cannot move
because a third-party library changed. The price is that some tests will run
only in the job that installs the extra, and a contributor who runs the bare
command sees them skip — the same failure mode as the BOILER cases, and it is
handled the same way, by declaring in `docs/goals/roadmap.json` which criteria
rest on evidence that does not always execute.

This amends the design plan's stack section, which specified one set managed by
`uv`. The tool is adopted; the single set is not.
