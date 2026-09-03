# Decision history

A chronological record of what was decided, what was found, and what was
deliberately not done — one entry per working session.

ADRs say what the standing decisions *are*. This says how they were arrived at:
the evidence that moved them, the numbers that came out of real files, and the
options rejected along the way. That second thing is what a reader six months
from now cannot reconstruct from the code, and what a fresh session would
otherwise re-derive from scratch.

## What goes in

Decisions and their reasoning. Findings, with the numbers. Options considered
and rejected, with why. Corrections — where something believed true turned out
not to be.

## What does not

Raw assistant transcripts, and anything from a customer's schedule: task names,
work-order or operation numbers, resource and work-centre codes, deployment
hostnames. The same rule as everywhere else in this repository — hashes and
sanitized structural findings only. Transcripts are kept outside the repository;
they contain schedule content verbatim, and this repository is public.

Counts, SHA-256 hashes, application build numbers and file sizes are fine, and
are usually the useful part anyway.
